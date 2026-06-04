"""
src/ecograph/computer_vision/model/mobilenet_encoder.py

Stand-alone re-export of MobileNetV3Encoder so that other modules can import
it directly from this file without going through unet.py.

This keeps the module boundary clean: unet.py owns the full network,
mobilenet_encoder.py is the public API for the encoder component.
"""

from ecograph.computer_vision.model.unet import MobileNetV3Encoder

__all__ = ["MobileNetV3Encoder"]