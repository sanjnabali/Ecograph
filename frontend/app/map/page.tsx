"use client";
/**
 * app/map/page.tsx - Supply chain world map.
 * Uses react-map-gl + MapLibre (free, no API key for basic map tiles via OpenFreeMap).
 */
import { useQuery } from "@tanstack/react-query";
import { useState, useMemo } from "react";
import { api, GeoNode } from "@/lib/api";
import ErrorBanner from "@/components/ErrorBanner";
import { labelHex, truncate } from "@/lib/utils";

// MapLibre / react-map-gl loaded dynamically (SSR-safe)
import dynamic from "next/dynamic";
const Map    = dynamic(() => import("react-map-gl/maplibre").then(m => m.default), { ssr: false });
const Marker = dynamic(() => import("react-map-gl/maplibre").then(m => m.Marker),  { ssr: false });
const Popup  = dynamic(() => import("react-map-gl/maplibre").then(m => m.Popup),   { ssr: false });

const MAP_STYLE = "https://tiles.openfreemap.org/styles/liberty";

// -- Colour dot for map markers -------------------------------------------
function Dot({ label, size = 14 }: { label: string; size?: number }) {
  return (
    <div
      style={{
        width:        size,
        height:       size,
        borderRadius: "50%",
        background:   labelHex(label),
        border:       "2px solid white",
        cursor:       "pointer",
        boxShadow:    "0 2px 6px rgba(0,0,0,0.5)",
      }}
    />
  );
}

export default function MapPage() {
  const geoQuery = useQuery({ queryKey: ["mapNodes"], queryFn: api.getMapNodes });
  const [popup, setPopup]             = useState<GeoNode | null>(null);
  const [labelFilter, setLabelFilter] = useState<string>("all");

  const labels = useMemo(() => {
    if (!geoQuery.data) return [];
    return ["all", ...Array.from(new Set(geoQuery.data.map((n: any) => n.label)))];
  }, [geoQuery.data]);

  const filtered = useMemo(() => {
    if (!geoQuery.data) return [];
    if (labelFilter === "all") return geoQuery.data;
    return geoQuery.data.filter((n: any) => n.label === labelFilter);
  }, [geoQuery.data, labelFilter]);

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-2xl font-bold text-white">Supply Chain Map</h1>
          <p className="text-gray-400 text-sm mt-1">
            {filtered.length} geocoded node{filtered.length !== 1 ? "s" : ""}
          </p>
        </div>

        {/* Label filter */}
        <div className="flex items-center gap-2 flex-wrap">
          {labels.map(l => (
            <button
              key={l}
              onClick={() => setLabelFilter(l)}
              className={`px-3 py-1 text-xs rounded-full border transition-colors ${
                labelFilter === l
                  ? "bg-brand-600 border-brand-600 text-white"
                  : "border-gray-700 text-gray-400 hover:border-gray-500"
              }`}
            >
              {l === "all" ? "All" : l}
            </button>
          ))}
        </div>
      </div>

      {geoQuery.error && <ErrorBanner error={geoQuery.error} onRetry={() => geoQuery.refetch()} />}

      {/* No data hint */}
      {!geoQuery.isLoading && !geoQuery.data?.length && !geoQuery.error && (
        <div className="bg-gray-900 border border-gray-800 rounded-xl p-8 text-center text-gray-500">
          <p className="text-4xl mb-3">🗺️</p>
          <p className="font-medium">No geocoded nodes yet.</p>
          <p className="text-sm mt-1">
            Run the pipeline (including geo enrichment) to populate the map.
          </p>
        </div>
      )}

      {/* Map */}
      {(geoQuery.isLoading || filtered.length > 0) && (
        <div className="rounded-xl overflow-hidden border border-gray-800" style={{ height: 560 }}>
          {geoQuery.isLoading ? (
            <div className="h-full bg-gray-900 flex items-center justify-center text-gray-600 animate-pulse">
              Loading map data...
            </div>
          ) : (
            <Map
              initialViewState={{ longitude: 0, latitude: 20, zoom: 1.8 }}
              style={{ width: "100%", height: "100%" }}
              mapStyle={MAP_STYLE}
            >
              {filtered.map((node: any, i: number) => (
                <Marker
                  key={`${node.name}-${i}`}
                  longitude={node.longitude}
                  latitude={node.latitude}
                  onClick={(e) => { e.originalEvent.stopPropagation(); setPopup(node); }}
                >
                  <Dot label={node.label} />
                </Marker>
              ))}

              {popup && (
                <Popup
                  longitude={popup.longitude}
                  latitude={popup.latitude}
                  anchor="bottom"
                  onClose={() => setPopup(null)}
                  closeButton
                  style={{ maxWidth: 220 }}
                >
                  <div className="text-gray-900 text-xs p-1">
                    <p className="font-bold text-sm">{popup.name}</p>
                    <p className="text-gray-600">{popup.label}</p>
                    <p className="font-mono text-gray-500">
                      {popup.latitude.toFixed(4)}, {popup.longitude.toFixed(4)}
                    </p>
                    {Object.entries(popup.extra).slice(0, 4).map(([k, v]) => (
                      <p key={k} className="text-gray-600">
                        <span className="font-medium">{k}:</span> {String(v)}
                      </p>
                    ))}
                  </div>
                </Popup>
              )}
            </Map>
          )}
        </div>
      )}

      {/* Legend */}
      {filtered.length > 0 && (
        <div className="flex flex-wrap gap-3">
          {Object.entries(labelHex).map(([label, hex]) => (
            <div key={label} className="flex items-center gap-1.5 text-xs text-gray-400">
              <div className="w-3 h-3 rounded-full" style={{ background: hex as string }} />
              {label}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}