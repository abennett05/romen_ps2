import { useMemo, useState } from "react";

// Palette of colors that look good in dark mode
const FALLBACK_COLORS = [
  "bg-red-900",
  "bg-blue-900",
  "bg-emerald-900",
  "bg-violet-900",
  "bg-amber-900",
  "bg-cyan-900",
  "bg-pink-900",
  "bg-slate-800"
];

interface GameCardProps {
    title: string;
    size: number;
    cover_url?: string
    onClick: () => void;
}

function GameCard({ title, size, cover_url, onClick } : GameCardProps) {
    const [imageError, setImageError] = useState(false);

    const randomColor = useMemo(() => {
        const randomIndex = Math.floor(Math.random() * FALLBACK_COLORS.length);
        return FALLBACK_COLORS[randomIndex];
    }, []);

    const formatSize = (bytes: number): string => {
        if (bytes === 0) return '0 Bytes';

        const k = 1024;
        const sizes = ['Bytes', 'KB', 'MB', 'GB', 'TB'];

        // Calculate which unit to use (0=Bytes, 1=KB, 2=MB, etc.)
        const i = Math.floor(Math.log(bytes) / Math.log(k));

        // Divide bytes by 1024^i and fix to 2 decimal places
        return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
    };

    return (
    <>
        <div onClick={onClick} className="group relative bg-zinc-900 rounded-lg overflow-hidden shadow-lg hover:shadow-2xl hover:scale-105 transition-all duration-300 cursor-pointer border border-zinc-800/50">
            <div className="hover:scale-101 transition-transform">
                {/* Image for the game card */}
                <div className={`relative aspect-2/3 w-full ${imageError ? randomColor : 'bg-zinc-900'}`}>
                    {!imageError && cover_url ? (
                        <img className="w-full h-full object-cover" 
                        src={cover_url} alt={title}
                        onError={() => setImageError(true)} />
                    ) : (
                        <div className="w-full h-full flex items-center justify-center p-4 text-center">
                          <h3 className="text-white font-bold text-lg opacity-80 uppercase tracking-widest">
                            {title}
                          </h3>
                        </div>
                    )}

                    <div className="absolute inset-0 bg-linear-to-t from-zinc-900/80 via-transparent to-transparent opacity-0 group-hover:opacity-100 transition-opacity duration-300" />
                </div>
                {/* Game title and other info */}
                <div className="bg-zinc-900 p-3">
                    <h2 className="font-bold text-xl text-gray-100 truncate">{title}</h2>
                    <p className="text-md text-gray-400">{formatSize(size)}</p>
                </div>
            </div>
        </div>
    </>
    );
}

export default GameCard;