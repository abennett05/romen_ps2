import React from "react";
import Modal from "../Modal";
import type { Game } from "../../App";
import { Trash2, HardDrive, Hash } from "lucide-react";

interface GameViewModalProps {
    isOpen: boolean;
    onClose: () => void;
    game: Game | null; // Allow null to prevent crashes when closing
    onDelete: (serial: string) => void; // Added this prop
}

const GameViewModal: React.FC<GameViewModalProps> = ({ isOpen, onClose, game, onDelete }) => {
    
    // 1. Guard clause: If no game is selected, render nothing
    if (!game) return null;

    // 2. Helper to format size (Same as in your GameCard)
    const formatSize = (bytes: number): string => {
        if (!bytes) return '0 Bytes';
        const k = 1024;
        const sizes = ['Bytes', 'KB', 'MB', 'GB', 'TB'];
        const i = Math.floor(Math.log(bytes) / Math.log(k));
        return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
    };

    // 3. Handle Delete Click
    const handleDelete = () => {
        if (confirm(`Are you sure you want to delete ${game.title}? This cannot be undone.`)) {
            onDelete(game.serial);
            onClose();
        }
    };

    return (
        <Modal isOpen={isOpen} onClose={onClose} title="Game Details">
            <div className="flex flex-col md:flex-row gap-6">
                
                {/* --- LEFT COLUMN: COVER ART --- */}
                <div className="w-full md:w-1/3 shrink-0">
                    <div className="aspect-2/3 w-full bg-zinc-800 rounded-lg overflow-hidden shadow-lg border border-zinc-700/50 relative">
                        {game.cover_url || (game as any).cover_URL ? (
                            <img 
                                src={game.cover_url || (game as any).cover_URL} 
                                alt={game.title} 
                                className="w-full h-full object-cover" 
                            />
                        ) : (
                            <div className="w-full h-full flex items-center justify-center text-zinc-600 font-bold">
                                NO COVER
                            </div>
                        )}
                    </div>
                </div>

                {/* --- RIGHT COLUMN: DETAILS & ACTIONS --- */}
                <div className="flex-1 flex flex-col">
                    
                    {/* Header */}
                    <h2 className="text-2xl font-bold text-white mb-1">{game.title}</h2>
                    <div className="h-1 w-20 bg-sky-600 rounded-full mb-6"></div>

                    {/* Stats Grid */}
                    <div className="grid grid-cols-1 gap-4 mb-8">
                        
                        {/* Serial Number */}
                        <div className="bg-zinc-800/50 p-3 rounded-md border border-zinc-700 flex items-center space-x-3">
                            <div className="p-2 bg-zinc-700 rounded-full text-zinc-300">
                                <Hash size={18} />
                            </div>
                            <div>
                                <p className="text-xs text-zinc-500 uppercase font-semibold">Serial Number</p>
                                <p className="text-zinc-200 font-mono tracking-wide">{game.serial}</p>
                            </div>
                        </div>

                        {/* File Size */}
                        <div className="bg-zinc-800/50 p-3 rounded-md border border-zinc-700 flex items-center space-x-3">
                            <div className="p-2 bg-zinc-700 rounded-full text-zinc-300">
                                <HardDrive size={18} />
                            </div>
                            <div>
                                <p className="text-xs text-zinc-500 uppercase font-semibold">File Size</p>
                                <p className="text-zinc-200">{formatSize(game.size)}</p>
                            </div>
                        </div>
                    </div>

                    {/* Push content to bottom */}
                    <div className="mt-auto pt-4 border-t border-zinc-800">
                        <button 
                            onClick={handleDelete}
                            className="w-full md:w-auto flex items-center justify-center space-x-2 bg-red-600/10 hover:bg-red-600 text-red-500 hover:text-white border border-red-600/20 hover:border-red-500 transition-all duration-200 py-2 px-4 rounded-md font-medium"
                        >
                            <Trash2 size={18} />
                            <span>Delete from Library</span>
                        </button>
                        <p className="text-xs text-zinc-600 mt-2 text-center md:text-left">
                            This action permanently removes the game from your libary & deletes all associated files.
                        </p>
                    </div>

                </div>
            </div>
        </Modal>
    );
}

export default GameViewModal;