import GameCard from "./GameCard"
import type { Game } from "../App";
import { Gamepad2, SearchX } from "lucide-react"; // Added SearchX for a "no results" state

interface GridProps {
    games: Game[];
    onGameClick: (game: Game) => void;
    filter: string | null;
}

export default function Grid({ games, onGameClick, filter }: GridProps) {
    // 1. Filter the games based on the title (case-insensitive)
    const filteredGames = games.filter((game) => {
        if (!filter) return true;
        return game.title.toLowerCase().includes(filter.toLowerCase());
    });

    return (
        <>
            {/* 2. Check if we have games to show after filtering */}
            {filteredGames.length > 0 ? (
                <div className="grid sm:grid-cols-2 md:grid-cols-4 lg:grid-cols-5 gap-10 p-5">
                    {filteredGames.map((game, index) => (
                        <GameCard 
                            key={index} 
                            title={game.title} 
                            size={game.size} 
                            cover_url={game.cover_url} 
                            onClick={() => onGameClick(game)}
                        />
                    ))}
                </div>
            ) : (
                <div className="flex flex-col items-center justify-center min-h-[50vh] text-zinc-500">
                    {/* 3. Logic to show different empty states */}
                    {games.length === 0 ? (
                        // Original "Empty Library" state
                        <>
                            <div className="bg-zinc-800/50 p-6 rounded-full mb-4 ring-1 ring-zinc-700/50">
                                <Gamepad2 size={48} className="text-zinc-600" />
                            </div>
                            <h2 className="text-2xl font-semibold text-zinc-300 mb-2">Got Games?</h2>
                            <p className="text-zinc-500 max-w-sm text-center mb-6">
                                Your library would appreciate some love.<br />
                                Upload an ISO file to get started.
                            </p>
                        </>
                    ) : (
                        // New "No Search Results" state
                        <>
                            <div className="bg-zinc-800/50 p-6 rounded-full mb-4 ring-1 ring-zinc-700/50">
                                <SearchX size={48} className="text-zinc-600" />
                            </div>
                            <h2 className="text-2xl font-semibold text-zinc-300 mb-2">No matches found</h2>
                            <p className="text-zinc-500 max-w-sm text-center mb-6">
                                We couldn't find any games matching "{filter}".
                            </p>
                        </>
                    )}
                </div>
            )}
        </>
    );
}