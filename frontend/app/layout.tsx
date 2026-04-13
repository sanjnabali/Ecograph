import type {Metadata} from "next";
import "./globals.css";
import Providers from "./providers";
import NavBar from "@/components/NavBar";


export const metadata: Metadata = {
    title: "Ecograph - Scope 3 Carbon Intelligence",
    description: "AI powered ESG knowledge graph for Scope 3 emissions analysis",
    icons: {icons: "/favicon.ico"},
};

export default function RootLayout({
    children,
}: {
    children: React.ReactNode;
}) {
    return (
        <html lang="en">
            <body className="bg-gray-950 text-gray-100 min-h-screen font-sans antialiased">
                <Providers>
                    <NavBar />
                    <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
                        {children}
                    </main>
                </Providers>
            </body>
        </html>
    );
}