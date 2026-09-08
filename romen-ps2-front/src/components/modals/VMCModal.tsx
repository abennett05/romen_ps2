import React, { useState } from 'react';
import Modal from '../Modal';
import type { Game } from '../../App';
import { useVMCs, formatBytes } from '../../hooks/useVMCs';
import { MemoryStick, Trash2, Plus, AlertTriangle, Loader2 } from 'lucide-react';

interface VMCModalProps {
    isOpen: boolean;
    onClose: () => void;
    games: Game[];
}

const VMCModal: React.FC<VMCModalProps> = ({ isOpen, onClose, games }) => {
    const { vmcs, sizes, loading, busy, createVMC, deleteVMC } = useVMCs(isOpen);
    const [newName, setNewName] = useState('');
    const [newSize, setNewSize] = useState(8);
    const [error, setError] = useState<string | null>(null);

    // Cards are stored by name, but people recognise their games by title.
    const titleFor = (serial: string) =>
        games.find((g) => g.serial === serial)?.title ?? serial;

    const handleCreate = async () => {
        setError(null);
        if (!newName.trim()) {
            setError('Give the card a name.');
            return;
        }
        const message = await createVMC(newName.trim(), newSize);
        if (message) {
            setError(message);
        } else {
            setNewName('');
        }
    };

    const handleDelete = async (name: string, assigned: string[]) => {
        const warning = assigned.length
            ? `\n\nIt is currently used by ${assigned.length} game(s). They will be unassigned.`
            : '';
        if (!confirm(`Delete the memory card "${name}"?${warning}\n\nAny saves on it are lost permanently.`)) return;
        const message = await deleteVMC(name);
        if (message) setError(message);
    };

    return (
        <Modal isOpen={isOpen} onClose={onClose} title="Memory Cards" maxWidth="max-w-2xl">
            <div className="flex flex-col space-y-5 max-h-[75vh] overflow-y-auto p-1">

                <p className="text-sm text-zinc-400">
                    Virtual Memory Cards let games save without a physical memory card.
                    Assign one to a game from its detail view.
                </p>

                {/* --- CREATE --- */}
                <div className="bg-zinc-800/50 border border-zinc-700 rounded-lg p-4">
                    <div className="flex flex-row items-center space-x-3 mb-3">
                        <Plus size={20} className="text-sky-500" />
                        <p className="font-semibold text-lg text-zinc-100">New Card</p>
                    </div>
                    <div className="flex flex-col sm:flex-row gap-2">
                        <input
                            className="flex-1 bg-zinc-900 border-2 border-zinc-600 focus:border-sky-500 text-zinc-100 rounded-lg p-2 transition-colors outline-none disabled:opacity-50"
                            type="text"
                            value={newName}
                            disabled={busy}
                            onChange={(e) => setNewName(e.target.value)}
                            onKeyDown={(e) => { if (e.key === 'Enter') handleCreate(); }}
                            placeholder="Card name"
                            maxLength={32}
                        />
                        <select
                            className="bg-zinc-900 border-2 border-zinc-600 focus:border-sky-500 text-zinc-100 rounded-lg p-2 outline-none disabled:opacity-50"
                            value={newSize}
                            disabled={busy}
                            onChange={(e) => setNewSize(Number(e.target.value))}
                        >
                            {sizes.map((s) => (
                                <option key={s} value={s}>{s} MB</option>
                            ))}
                        </select>
                        <button
                            onClick={handleCreate}
                            disabled={busy}
                            className="flex items-center justify-center space-x-2 bg-sky-600 hover:bg-sky-500 disabled:opacity-50 disabled:hover:bg-sky-600 text-white transition-colors py-2 px-4 rounded-lg font-medium"
                        >
                            {busy ? <Loader2 size={18} className="animate-spin" /> : <Plus size={18} />}
                            <span>Create</span>
                        </button>
                    </div>
                    <p className="text-xs text-zinc-600 mt-2">
                        8 MB matches a real PlayStation 2 memory card. Larger cards hold more
                        saves but a few games refuse to use them.
                    </p>
                </div>

                {error && (
                    <div className="flex items-start space-x-2 bg-red-600/10 border border-red-600/30 text-red-400 rounded-lg p-3 text-sm">
                        <AlertTriangle size={18} className="shrink-0 mt-0.5" />
                        <span>{error}</span>
                    </div>
                )}

                {/* --- LIST --- */}
                <div className="flex flex-col space-y-2">
                    {loading && (
                        <div className="flex items-center justify-center space-x-2 text-zinc-500 py-8">
                            <Loader2 size={18} className="animate-spin" />
                            <span>Reading cards...</span>
                        </div>
                    )}

                    {!loading && vmcs.length === 0 && (
                        <div className="text-center text-zinc-600 py-8">
                            <MemoryStick size={40} className="mx-auto mb-2 opacity-40" />
                            <p>No memory cards yet.</p>
                        </div>
                    )}

                    {vmcs.map((vmc) => {
                        const used = (vmc.size ?? 0) - (vmc.free_bytes ?? 0);
                        const percent = vmc.size ? Math.min(100, (used / vmc.size) * 100) : 0;
                        return (
                            <div
                                key={vmc.name}
                                className="bg-zinc-800/50 border border-zinc-700 rounded-lg p-3 flex items-center space-x-4"
                            >
                                <div className={`p-2 rounded-full shrink-0 ${vmc.valid ? 'bg-zinc-700 text-sky-400' : 'bg-red-900/30 text-red-400'}`}>
                                    <MemoryStick size={22} />
                                </div>

                                <div className="flex-1 min-w-0">
                                    <div className="flex items-baseline space-x-2">
                                        <p className="text-zinc-100 font-semibold truncate">{vmc.name}</p>
                                        <span className="text-xs text-zinc-500 shrink-0">{vmc.size_mb} MB</span>
                                    </div>

                                    {vmc.valid ? (
                                        <>
                                            <div className="h-1.5 w-full bg-zinc-900 rounded-full overflow-hidden my-1.5">
                                                <div
                                                    className="h-full bg-sky-600 rounded-full transition-all"
                                                    style={{ width: `${percent}%` }}
                                                />
                                            </div>
                                            <p className="text-xs text-zinc-500">
                                                {formatBytes(vmc.free_bytes)} free
                                                {vmc.assigned_to.length > 0 && (
                                                    <span className="text-zinc-400">
                                                        {' · '}
                                                        {vmc.assigned_to.map(titleFor).join(', ')}
                                                    </span>
                                                )}
                                                {vmc.assigned_to.length === 0 && (
                                                    <span className="text-amber-500/70">{' · '}not assigned to a game</span>
                                                )}
                                            </p>
                                        </>
                                    ) : (
                                        <p className="text-xs text-red-400 mt-1 flex items-center space-x-1">
                                            <AlertTriangle size={12} />
                                            <span>{vmc.reason ?? 'Not a valid memory card.'}</span>
                                        </p>
                                    )}
                                </div>

                                <button
                                    onClick={() => handleDelete(vmc.name, vmc.assigned_to)}
                                    disabled={busy}
                                    title="Delete card"
                                    className="shrink-0 p-2 rounded-md text-red-500/70 hover:text-white hover:bg-red-600 disabled:opacity-40 transition-colors"
                                >
                                    <Trash2 size={18} />
                                </button>
                            </div>
                        );
                    })}
                </div>
            </div>
        </Modal>
    );
};

export default VMCModal;
