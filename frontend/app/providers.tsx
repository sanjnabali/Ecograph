"use client";
/**
 * app/providers.tsx - React query provider for the entire app
 * Wraps the entire app so any component can use useQuery/useMutation.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {useState} from "react";

export default function Providers({ children }: { children: React.ReactNode }) {
    const [queryClient] = useState(
        () => new QueryClient({
            defaultOptions: {
                queries: {
                    staleTime:  30_000,
                    retry:      1,
                    refetchOnWindowFocus: false,
                },
            },
        })
    );

    return(
        <QueryClientProvider client={queryClient}>
            {children}
        </QueryClientProvider>
    );
}

    