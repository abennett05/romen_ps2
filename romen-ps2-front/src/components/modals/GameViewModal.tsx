import React, { useEffect, useState } from "react";
import Modal from "../Modal";
import type { Game } from "../../App";
import { Trash2, HardDrive, Hash, MemoryStick, Plus, Loader2 } from "lucide-react";
import { useVMCs, assignVMC, unassignVMC, fetchAssignments } from "../../hooks/useVMCs";

interface GameViewModalProps {
    isOpen: boolean;
    onClose: () => void;
    game: Game | null; 
    onDelete: (serial: string) => void;
}

const SLOTS = [0, 1];

const GameViewModal: React.FC<GameViewModalProps> = ({ isOpen, onClose, game, onDelete }) => {
    
    // REMOVED: if (!game) return null; 
    // ^ This was killing the component before the Modal could unlock the scrollbar.

    const { vmcs, createVMC, refresh, busy } = useVMCs(isOpen);
    const [slots, setSlots] = useState<Record<string, string | null>>({});
    const [slotsLoading, setSlotsLoading] = useState(false);

    // Slot assignments live in the game's CFG file, not the library database,
    // so they're read fresh each time the game is opened.
    useEffect(() => {
        if (!isOpen || !game) return;
        let cancelled = false;
        setSlotsLoading(true);
        fetchAssignments(game.serial)
            .then((data) => { if (!cancelled) setSlots(data); })
            .catch((error) => console.error("Failed to fetch VMC slots: ", error))
            .finally(() => { if (!cancelled) setSlotsLoading(false); });
        return () => { cancelled = true; };
    }, [isOpen, game]);

    const formatSize = (bytes: number): string => {
        if (!bytes) return '0 Bytes';
        const k = 1024;
        const sizes = ['Bytes', 'KB', 'MB', 'GB', 'TB'];
        const i = Math.floor(Math.log(bytes) / Math.log(k));
        return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
    };

    const handleDelete = () => {
        // Added 'game &&' check here because we removed the top guard clause
        if (game && confirm(`Are you sure you want to delete ${game.title}? This cannot be undone.`)) {
            onDelete(game.serial);
            onClose();
        }
    };

    const handleSlotChange = async (slot: number, name: string) => {
        if (!game) return;
        const previous = slots;
        setSlots({ ...slots, [String(slot)]: name || null });
        try {
            const result = name
                ? await assignVMC(game.serial, name, slot)
                : await unassignVMC(game.serial, slot);
            if (result.status !== "success") {
                setSlots(previous);
                alert(result.message ?? "Failed to update memory card slot.");
            }
        } catch (error) {
            console.error(error);
            setSlots(previous);
            alert("Failed to reach server.");
        }
    };

    // Shortcut for the common case: one card, named after this game, in slot 1.
    const handleCreateForGame = async () => {
        if (!game) return;
        const name = game.serial.replace(/_/g, '-').replace(/\./g, '').toUpperCase();
        const message = await createVMC(name, 8);
        if (message) {
            alert(message);
            return;
        }
        await handleSlotChange(0, name);
        refresh();
    };

    const usableVmcs = vmcs.filter((v) => v.valid);

    return (
        <Modal isOpen={isOpen} onClose={onClose} title="Game Details" maxWidth="max-w-lg">
            {/* We check if game exists here instead. 
                If game is null, we render nothing inside, but the Modal wrapper still exists 
                to handle the closing logic. */}
            {game ? (
                // Added max-h-[80vh] and overflow-y-auto to fix internal scrolling
                <div className="flex flex-col md:flex-row gap-6 max-h-[80vh] overflow-y-auto p-1">
                    
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
                    <div className="flex-1 flex flex-col min-w-0">
                        
                        <h2 className="text-2xl font-bold text-white mb-1 break-words">{game.title}</h2>
                        <div className="h-1 w-20 bg-sky-600 rounded-full mb-6"></div>

                        <div className="grid grid-cols-1 gap-4 mb-6">
                            <div className="bg-zinc-800/50 p-3 rounded-md border border-zinc-700 flex items-center space-x-3">
                                <div className="p-2 bg-zinc-700 rounded-full text-zinc-300">
                                    <Hash size={18} />
                                </div>
                                <div>
                                    <p className="text-xs text-zinc-500 uppercase font-semibold">Serial Number</p>
                                    <p className="text-zinc-200 font-mono tracking-wide">{game.serial}</p>
                                </div>
                            </div>

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

                        {/* --- MEMORY CARDS --- */}
                        <div className="mb-6">
                            <div className="flex items-center space-x-2 mb-3">
                                <MemoryStick size={18} className="text-zinc-400" />
                                <p className="text-xs text-zinc-500 uppercase font-semibold">Memory Cards</p>
                            </div>

                            {slotsLoading ? (
                                <div className="flex items-center space-x-2 text-zinc-600 text-sm py-2">
                                    <Loader2 size={14} className="animate-spin" />
                                    <span>Reading slots...</span>
                                </div>
                            ) : usableVmcs.length === 0 ? (
                                <button
                                    onClick={handleCreateForGame}
                                    disabled={busy}
                                    className="w-full flex items-center justify-center space-x-2 bg-sky-600/10 hover:bg-sky-600 text-sky-400 hover:text-white border border-sky-600/20 hover:border-sky-500 disabled:opacity-50 transition-all duration-200 py-2 px-4 rounded-md font-medium text-sm"
                                >
                                    {busy ? <Loader2 size={16} className="animate-spin" /> : <Plus size={16} />}
                                    <span>Create an 8 MB card for this game</span>
                                </button>
                            ) : (
                                <div className="space-y-2">
                                    {SLOTS.map((slot) => (
                                        <div key={slot} className="flex items-center space-x-3">
                                            <span className="text-sm text-zinc-500 w-14 shrink-0">Slot {slot + 1}</span>
                                            <select
                                                value={slots[String(slot)] ?? ''}
                                                onChange={(e) => handleSlotChange(slot, e.target.value)}
                                                className="flex-1 min-w-0 bg-zinc-800 border border-zinc-700 focus:border-sky-500 text-zinc-200 text-sm rounded-md p-2 outline-none transition-colors"
                                            >
                                                <option value="">None — use a real card</option>
                                                {usableVmcs.map((vmc) => (
                                                    <option key={vmc.name} value={vmc.name}>
                                                        {vmc.name} ({vmc.size_mb} MB)
                                                    </option>
                                                ))}
                                            </select>
                                        </div>
                                    ))}
                                </div>
                            )}
                        </div>

                        <div className="mt-auto pt-4 border-t border-zinc-800">
                            <button 
                                onClick={handleDelete}
                                className="w-full md:w-auto flex items-center justify-center space-x-2 bg-red-600/10 hover:bg-red-600 text-red-500 hover:text-white border border-red-600/20 hover:border-red-500 transition-all duration-200 py-2 px-4 rounded-md font-medium"
                            >
                                <Trash2 size={18} />
                                <span>Delete from Library</span>
                            </button>
                            <p className="text-xs text-zinc-600 mt-2 text-center md:text-left">
                                This action permanently removes the game from your library &amp; deletes all associated files.
                                Memory cards are kept, so your saves are safe.
                            </p>
                        </div>
                    </div>
                </div>
            ) : (
                // Fallback content (optional, prevents visual glitch during close animation)
                <div className="h-64 flex items-center justify-center text-zinc-500">
                    Loading details...
                </div>
            )}
        </Modal>
    );
}

export default GameViewModal;
