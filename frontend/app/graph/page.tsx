"use client";
/**
 * app/graph/page.tsx - Interactive Knowledge Graph Explorer.
 * Uses react-force-graph-2d (canvas-based, handles thousands of nodes smoothly).
 * Loaded dynamically because it requires window/canvas (no SSR).
 */
import { useQuery } from "@tanstack/react-query";
import { useState, useCallback } from "react";
import dynamic from "next/dynamic";
import { api, NodeOut, EdgeOut, NodeDetail } from "@/lib/api";
import ErrorBanner from "@/components/ErrorBanner";
import { labelHex, labelColour, truncate } from "@/lib/utils";

const ForceGraph2D = dynamic(() => import("react-force-graph-2d"), { ssr: false });

// -- Sidebar: node detail panel -------------------------------------------
function NodePanel({ detail, onClose }: { detail: NodeDetail; onClose: () => void }) {
  return (
    <div className="bg-gray-900 border border-gray-700 rounded-xl p-4 space-y-3 text-sm">
      <div className="flex items-start justify-between">
        <div>
          <span className={`text-xs px-2 py-0.5 rounded-full ${labelColour(detail.node.label)}`}>
            {detail.node.label}
          </span>
          <h3 className="text-white font-bold mt-1 text-base">{detail.node.name}</h3>
        </div>
        <button onClick={onClose} className="text-gray-500 hover:text-white text-lg leading-none">×</button>
      </div>

      {/* Properties */}
      {Object.keys(detail.node.properties).length > 0 && (
        <div>
          <p className="text-gray-500 text-xs uppercase tracking-wide mb-1">Properties</p>
          <div className="space-y-1">
            {Object.entries(detail.node.properties)
              .filter(([k]) => !["_is_new", "_new_node", "geocode_failed"].includes(k))
              .map(([k, v]) => (
                <div key={k} className="flex gap-2">
                  <span className="text-gray-500 font-mono text-xs w-28 shrink-0">{k}</span>
                  <span className="text-gray-300 text-xs break-all">{String(v)}</span>
                </div>
              ))}
          </div>
        </div>
      )}

      {/* Relationships */}
      {detail.relationships.length > 0 && (
        <div>
          <p className="text-gray-500 text-xs uppercase tracking-wide mb-1">
            Relationships ({detail.relationships.length})
          </p>
          <div className="space-y-1 max-h-48 overflow-y-auto">
            {detail.relationships.map((r, i) => (
              <div key={i} className="text-xs text-gray-400 flex items-center gap-1">
                <span className="text-gray-600">{r.source === detail.node.id ? "→" : "←"}</span>
                <span className="bg-gray-800 px-1.5 py-0.5 rounded font-mono text-gray-300">{r.type}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

// -- Main page ------------------------------------------------------------
export default function GraphPage() {
  const [search, setSearch]                 = useState("");
  const [hops,     setHops]                 = useState<1 | 2 | 3>(1);
  const [selectedDetail, setDetail]         = useState<NodeDetail | null>(null);
  const [loadingNode,    setLoading]        = useState(false);
  const [subgraphName,   setSubgraphName]   = useState<string | null>(null);

  // Supply chain as default view
  const supplyChainQ = useQuery({
    queryKey: ["supplyChain"],
    queryFn:  () => api.getSupplyChain(300),
  });

  // Subgraph for selected node
  const subgraphQ = useQuery({
    queryKey: ["subgraph", subgraphName, hops],
    queryFn:  () => api.getSubgraph(subgraphName!, hops),
    enabled:  !!subgraphName,
  });

  const graphData = subgraphName
    ? subgraphQ.data
    : supplyChainQ.data;

  // Convert to react-force-graph format
  const fgData = graphData
    ? {
        nodes: graphData.nodes.map((n: NodeOut) => ({
          id:    n.id,
          name:  n.name,
          label: n.label,
          color: labelHex(n.label),
          val:   n.label === "Company" ? 6 : 3,
        })),
        links: graphData.edges.map((e: EdgeOut) => ({
          source: e.source,
          target: e.target,
          label:  e.type,
        })),
      }
    : { nodes: [], links: [] };

  const handleNodeClick = useCallback(async (node: { id: string; name: string; label: string }) => {
    setLoading(true);
    try {
      const detail = await api.getNode(node.name, node.label);
      setDetail(detail);
    } catch (err) {
      console.error("Node fetch error:", err);
    } finally {
      setLoading(false);
    }
  }, []);

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault();
    if (search.trim()) {
      setSubgraphName(search.trim());
      setDetail(null);
    }
  };

  const isLoading = (subgraphName ? subgraphQ : supplyChainQ).isLoading;
  const error     = (subgraphName ? subgraphQ : supplyChainQ).error;

  return (
    <div className="space-y-4">
      <div className="flex items-start justify-between flex-wrap gap-4">
        <div>
          <h1 className="text-2xl font-bold text-white">Knowledge Graph</h1>
          <p className="text-gray-400 text-sm mt-1">
            {fgData.nodes.length} nodes • {fgData.links.length} edges
            {subgraphName && <span> • subgraph of <em className="text-brand-400">{subgraphName}</em></span>}
          </p>
        </div>

        {/* Search + controls */}
        <div className="flex items-center gap-2 flex-wrap">
          {subgraphName && (
            <button
              onClick={() => { setSubgraphName(null); setDetail(null); }}
              className="text-xs text-gray-400 hover:text-white px-2 py-1 border border-gray-700 rounded"
            >
              ← Full graph
            </button>
          )}
          <form onSubmit={handleSearch} className="flex gap-2">
            <input
              value={search}
              onChange={e => setSearch(e.target.value)}
              placeholder="Company name..."
              className="bg-gray-800 border border-gray-700 text-white text-sm px-3 py-1.5 rounded-lg placeholder-gray-500 focus:outline-none focus:border-brand-500 w-52"
            />
            <select
              value={hops}
              onChange={e => setHops(Number(e.target.value) as 1 | 2 | 3)}
              className="bg-gray-800 border border-gray-700 text-gray-300 text-sm px-2 py-1.5 rounded-lg"
            >
              <option value={1}>1 hop</option>
              <option value={2}>2 hops</option>
              <option value={3}>3 hops</option>
            </select>
            <button
              type="submit"
              className="bg-brand-600 hover:bg-brand-700 text-white text-sm px-4 py-1.5 rounded-lg transition-colors"
            >
              Explore
            </button>
          </form>
        </div>
      </div>

      {error && <ErrorBanner error={error} />}

      <div className="flex gap-4">
        {/* Graph canvas */}
        <div className="flex-1 bg-gray-950 border border-gray-800 rounded-xl overflow-hidden" style={{ height: 560 }}>
          {isLoading ? (
            <div className="h-full flex items-center justify-center text-gray-600 animate-pulse">
              Loading graph...
            </div>
          ) : !fgData.nodes.length ? (
            <div className="h-full flex flex-col items-center justify-center text-gray-600">
              <p className="text-4xl mb-3">🕸️</p>
              <p className="font-medium">No graph data yet.</p>
              <p className="text-sm mt-1">Run the pipeline first to populate the graph.</p>
            </div>
          ) : (
            <ForceGraph2D
              graphData={fgData}
              nodeLabel="name"
              nodeColor={(n: { color?: string }) => n.color ?? "#6b7280"}
              nodeVal={(n: { val?: number }) => n.val ?? 4}
              linkLabel={(l: { label?: string }) => l.label ?? ""}
              linkColor={() => "#374151"}
              backgroundColor="#030712"
              onNodeClick={(node: { id: string; name: string; label: string }) => handleNodeClick(node)}
              nodeCanvasObject={(node: { x?: number; y?: number; color?: string; val?: number; name?: string }, ctx, globalScale) => {
                const r = (node.val ?? 4) * 1.2;
                const x = node.x ?? 0;
                const y = node.y ?? 0;
                ctx.beginPath();
                ctx.arc(x, y, r, 0, 2 * Math.PI);
                ctx.fillStyle = node.color ?? "#6b7280";
                ctx.fill();
                if (globalScale > 2 && node.name) {
                  ctx.fillStyle = "#f9fafb";
                  ctx.font = `${10 / globalScale}px Inter, sans-serif`;
                  ctx.textAlign = "center";
                  ctx.fillText(truncate(node.name, 20), x, y + r + 8 / globalScale);
                }
              }}
            />
          )}
          {loadingNode && (
            <div className="absolute inset-0 flex items-center justify-center bg-black/40 rounded-xl">
              <div className="text-white text-sm">Loading node...</div>
            </div>
          )}
        </div>

        {/* Sidebar */}
        {selectedDetail && (
          <div className="w-72 shrink-0">
            <NodePanel detail={selectedDetail} onClose={() => setDetail(null)} />
          </div>
        )}
      </div>

      {/* Legend */}
      <div className="flex flex-wrap gap-3">
        {Object.entries(labelHex).map(([label, hex]) => (
          <div key={label} className="flex items-center gap-1.5 text-xs text-gray-400">
            <div className="w-3 h-3 rounded-full" style={{ background: hex as string }} />
            {label}
          </div>
        ))}
      </div>
    </div>
  );
}