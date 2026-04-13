"use client";

/**
 * components/ErrorBanner.tsx - Reusable error state component.
 * Shows the ApiError message and a retry button.
 */

import { ApiError } from "@/lib/api";

interface Props{
    error: unknown;
    onRetry: () => void;
}

export default function ErrorBanner({ error, onRetry }: Props) {
    const isApiError  = error instanceof ApiError;
    const status = isApiError ? error.status : 0;
    const message = isApiError ? error.message : "An unexpected error occurred.";
    const code = isApiError ? error.code : "UNKNOWN_ERROR";

    const isOffline = status === 0;
    const isDbDown = status === 503;
    const isNotFound = status === 404;

    const hint = isOffline
        ? "Make sure the fastapi backend is running: uvicorn api.main:app --reload"
        : isDbDown
        ? "Neo4j is not reachable. Check your .env and the Neo4j Desktop / auth Db is running"
        : isNotFound
        ? "The requested resource was not found. Check the API endpoint and parameters."
        : null;

    return (
        <div className="rounded-lg border border-red-200 bg-red-50 p-4">
            <div className="flex items-start gap-3">
                <span className="text-red-500 text-x1"></span>
                <div className="flex-1">
                    <p className="font-semibold text-red-800 text-sm">
                        {isOffline ? "Cannot reach API": isDbDown ? "Database Unreachable" : "Error"}
                        {status > 0 && <span className="ml-2 font-mono text-xs text-red-500">{status}</span>}
                    </p>
                    <p className="text-red-600 text-sm mt-0.5">{message}</p>
                    {hint && (
                        <p className="text-red-600 text-xs mt-1 font-mono bg-red-100 rounded px-2 py-1>
                        {hint}
                        </p>
                    )}
                    {code !== "unkown_error" && (
                        <p className="text-red-400 text-xs mt-1">code: {code}</p>
                    )}
            </div>
            {onRetry && (
                <button onClick={onRetry}
                className="shrink-0 text-xs bg-red-100 hover:bg-red-200 text-red-800
                px-3 py-1 rounded-md transition-colors"
                >
                    Retry
                </button>
            )}
        </div>
        </div>
    );
}