from __future__ import annotations

import logging
from typing import List

import torch
import torch.nn as nn
import torch.nn.functional as F

logger = logging.getLogger(__name__)


# -----------------------------------------------------------------------------
# Helper blocks
# -----------------------------------------------------------------------------
class _ConvBnReLU(nn.Sequential):
    """3x3 conv -> BatchNorm -> ReLU."""
    def __init__(self, in_ch: int, out_ch: int, *, stride: int = 1):
        super().__init__(
            nn.Conv2d(in_ch, out_ch, 3, stride=stride, padding=1, bias=False),
            nn.BatchNorm2d(out_ch),
            nn.ReLU(inplace=True),
        )


class _DecoderBlock(nn.Module):
    """Bilinear 2x upsample + skip connection + two conv blocks."""
    def __init__(self, in_ch: int, skip_ch: int, out_ch: int):
        super().__init__()
        self.upsample = nn.Upsample(
            scale_factor=2, mode="bilinear", align_corners=False
        )
        self.conv = nn.Sequential(
            _ConvBnReLU(in_ch + skip_ch, out_ch),
            _ConvBnReLU(out_ch, out_ch),
        )

    def forward(self, x: torch.Tensor, skip: torch.Tensor) -> torch.Tensor:
        x = self.upsample(x)
        # Pad if spatial dims differ by 1 pixel (odd input sizes)
        if x.shape[-2:] != skip.shape[-2:]:
            x = F.pad(
                x,
                [0, skip.shape[-1] - x.shape[-1], 0, skip.shape[-2] - x.shape[-2]],
            )
        return self.conv(torch.cat([x, skip], dim=1))


# -----------------------------------------------------------------------------
# MobileNetV3-Small encoder
# -----------------------------------------------------------------------------
class MobileNetV3Encoder(nn.Module):
    """
    MobileNetV3-Small feature extractor.
    Returns 4 intermediate feature maps at strides 2, 4, 8, 16
    for use as U-Net skip connections.
    output_channels : [16, 24, 48, 96]
    """
    output_channels: List[int] = [16, 24, 48, 96]

    def __init__(self, *, pretrained: bool = True):
        super().__init__()
        try:
            from torchvision.models import mobilenet_v3_small, MobileNet_V3_Small_Weights
            weights = MobileNet_V3_Small_Weights.DEFAULT if pretrained else None
            base = mobilenet_v3_small(weights=weights)
        except ImportError as exc:
            raise ImportError("torchvision is required for MobileNetV3Encoder.") from exc

        features = base.features  # type: ignore[attr-defined]
        # Feature map checkpoints (output stride -> feature index)
        # stride 2:  features[0]        (16-ch)
        # stride 4:  features[1]        (16-ch -> 24-ch)  idx 1-2
        # stride 8:  features[3]        (24-ch -> 48-ch)  idx 3-5
        # stride 16: features[6]        (48-ch -> 96-ch)  idx 6-12
        self.enc0 = nn.Sequential(*features[:2])   # -> 16 ch, stride 2
        self.enc1 = nn.Sequential(*features[2:4])  # -> 24 ch, stride 4
        self.enc2 = nn.Sequential(*features[4:7])  # -> 48 ch, stride 8
        self.enc3 = nn.Sequential(*features[7:13]) # -> 96 ch, stride 16

        # Replace first conv to accept 4-channel input
        old_conv: nn.Conv2d = self.enc0[0][0] # features[0].0 is the first conv
        self.enc0[0][0] = nn.Conv2d(
            4,
            old_conv.out_channels,
            kernel_size=old_conv.kernel_size,
            stride=old_conv.stride,
            padding=old_conv.padding,
            bias=False,
        )
        nn.init.kaiming_normal_(self.enc0[0][0].weight, mode="fan_out")
        logger.debug("MobileNetV3Encoder initialised (pretrained=%s).", pretrained)

    def forward(
        self, x: torch.Tensor
    ) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor, torch.Tensor]:
        f0 = self.enc0(x)     # stride 2
        f1 = self.enc1(f0)    # stride 4
        f2 = self.enc2(f1)    # stride 8
        f3 = self.enc3(f2)    # stride 16
        return f0, f1, f2, f3


# -----------------------------------------------------------------------------
# U-Net
# -----------------------------------------------------------------------------
class EcoGraphUNet(nn.Module):
    """
    Full U-Net with injected encoder.

    Parameters
    ----------
    encoder:
        Any module that returns 4 feature tensors at strides 2,4,8,16.
        Defaults to MobileNetV3Encoder(pretrained=True).
    pretrained_encoder:
        Only used when `encoder` is None.
    """
    def __init__(
        self,
        encoder: nn.Module | None = None,
        *,
        pretrained_encoder: bool = True,
    ):
        super().__init__()
        self.encoder: nn.Module = (
            encoder if encoder is not None
            else MobileNetV3Encoder(pretrained=pretrained_encoder)
        )
        ch = self.encoder.output_channels  # type: ignore[attr-defined]

        # Bottleneck at stride 16
        self.bottleneck = nn.Sequential(
            _ConvBnReLU(ch[3], 256),
            _ConvBnReLU(256, 256),
        )

        # Decoder blocks
        self.dec3 = _DecoderBlock(256, ch[2], 128)
        self.dec2 = _DecoderBlock(128, ch[1], 64)
        self.dec1 = _DecoderBlock(64, ch[0], 32)
        # Final up-sample to original resolution (stride 1) – no skip here
        self.dec0 = nn.Sequential(
            nn.Upsample(scale_factor=2, mode="bilinear", align_corners=False),
            _ConvBnReLU(32, 16),
        )
        self.head = nn.Conv2d(16, 1, kernel_size=1)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        f0, f1, f2, f3 = self.encoder(x)
        b = self.bottleneck(f3)
        d3 = self.dec3(b, f2)
        d2 = self.dec2(d3, f1)
        d1 = self.dec1(d2, f0)
        d0 = self.dec0(d1)
        return torch.sigmoid(self.head(d0))

    # Convenience Factory
    @classmethod
    def from_checkpoint(cls, path: str, *, device: str = "cpu") -> "EcoGraphUNet":
        """Load a saved state-dict from `path`."""
        model = cls(pretrained_encoder=False)
        state = torch.load(path, map_location=device)
        model.load_state_dict(state)
        model.eval()
        logger.info("EcoGraphUNet loaded from %s.", path)
        return model