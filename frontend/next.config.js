/**@type {import('next').NextConfig} */
const nextConfig = {
    async rewrites(){
        return[
            {
                source: "/api/:path*",
                destination: `${process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"}/api/:path*`,
            },
        ];
    },

    async header(){
        return [
            {
                source: "/(.*)",
                headers: [
                    {key: "X-Frame-Options",     value: "DENY"},
                    {Key: "X-Content-Type-Options", value: "nosniff"},
                    {key: "Referrer-Policy", value: "strict-origin-when-cross-origin"},
                ],
            },
        ];
    },

};

module.exports = nextConfig