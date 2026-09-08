import React, { useEffect, useState } from 'react';
import Modal from '../Modal';
import { browseVMC, formatBytes } from '../../hooks/useVMCs';
import type { VMCContents, VMCSave } from '../../hooks/useVMCs';
import { AlertTriangle, ChevronDown, FileText, Loader2, MemoryStick, Save } from 'lucide-react';

interface SaveBrowserModalProps {
    isOpen: boolean;
    onClose: () => void;
    vmcName: string | null;
}

// A save's own icon.sys title is often just "SAVE DATA", so the game title from
// the library database leads and the icon title fills in behind it.
const primaryLabel = (save: VMCSave) => save.title ?? save.icon_title ?? save.folder;
const secondaryLabel = (save: VMCSave) => {
    const primary = primaryLabel(save);
    if (save.icon_title && save.icon_title !== primary) return save.icon_title;
    return save.folder;
};

const SaveCard: React.FC<{ save: VMCSave }> = ({ save }) => {
    const [imageError, setImageError] = useState(false);
    const [expanded, setExpanded] = useState(false);
    const showCover = save.cover_url && !imageError;

    return (
        <div className="bg-zinc-800/50 border border-zinc-700 rounded-lg overflow-hidden">
            <button
                onClick={() => setExpanded(!expanded)}
                className="w-full text-left group"
            >
                <div className="relative aspect-2/3 w-full bg-zinc-900">
                    {showCover ? (
                        <img
                            className="w-full h-full object-cover"
                            src={save.cover_url!}
                            alt={primaryLabel(save)}
                            onError={() => setImageError(true)}
                        />
                    ) : (
                        <div className="w-full h-full flex flex-col items-center justify-center p-3 text-center">
                            <Save size={28} className="text-zinc-700 mb-2" />
                            <span className="text-zinc-500 text-xs font-medium uppercase tracking-wider break-all">
                                {save.folder}
                            </span>
                        </div>
                    )}
                    <div className="absolute inset-x-0 bottom-0 bg-linear-to-t from-zinc-900 to-transparent h-1/3" />
                </div>

                <div className="p-2.5">
                    <p className="text-zinc-100 text-sm font-semibold truncate" title={primaryLabel(save)}>
                        {primaryLabel(save)}
                    </p>
                    <p className="text-xs text-zinc-500 truncate" title={secondaryLabel(save)}>
                        {secondaryLabel(save)}
                    </p>
                    <div className="flex items-center justify-between mt-1.5">
                        <span className="text-xs text-zinc-400">{formatBytes(save.size)}</span>
                        <span className="flex items-center space-x-1 text-xs text-zinc-600 group-hover:text-zinc-400 transition-colors">
                            <span>{save.file_count} file{save.file_count === 1 ? '' : 's'}</span>
                            <ChevronDown
                                size={13}
                                className={`transition-transform ${expanded ? 'rotate-180' : ''}`}
                            />
                        </span>
                    </div>
                </div>
            </button>

            {expanded && (
                <div className="border-t border-zinc-700 bg-zinc-900/50 p-2.5 space-y-1">
                    {save.modified && (
                        <p className="text-xs text-zinc-500 pb-1">
                            Last saved {save.modified.replace('T', ' ')}
                        </p>
                    )}
                    {save.files.map((file) => (
                        <div key={file.name} className="flex items-center space-x-2 text-xs">
                            <FileText size={12} className="text-zinc-600 shrink-0" />
                            <span className="text-zinc-400 truncate flex-1">{file.name}</span>
                            <span className="text-zinc-600 shrink-0">{formatBytes(file.size)}</span>
                        </div>
                    ))}
                </div>
            )}
        </div>
    );
};

const SaveBrowserModal: React.FC<SaveBrowserModalProps> = ({ isOpen, onClose, vmcName }) => {
    const [contents, setContents] = useState<VMCContents | null>(null);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState<string | null>(null);

    useEffect(() => {
        if (!isOpen || !vmcName) return;
        let cancelled = false;

        setLoading(true);
        setError(null);
        setContents(null);
        browseVMC(vmcName)
            .then((data) => { if (!cancelled) setContents(data); })
            .catch((e) => { if (!cancelled) setError(e.message ?? 'Could not read that card.'); })
            .finally(() => { if (!cancelled) setLoading(false); });

        return () => { cancelled = true; };
    }, [isOpen, vmcName]);

    const used = (contents?.size ?? 0) - (contents?.free_bytes ?? 0);
    const percent = contents?.size ? Math.min(100, (used / contents.size) * 100) : 0;

    return (
        <Modal
            isOpen={isOpen}
            onClose={onClose}
            title={vmcName ?? 'Memory Card'}
            maxWidth="max-w-4xl"
        >
            <div className="flex flex-col space-y-5 max-h-[75vh] overflow-y-auto p-1">

                {contents && (
                    <div className="bg-zinc-800/50 border border-zinc-700 rounded-lg p-4">
                        <div className="flex items-center justify-between mb-2">
                            <div className="flex items-center space-x-3">
                                <MemoryStick size={20} className="text-sky-500" />
                                <span className="text-zinc-100 font-semibold">
                                    {contents.saves.length} save{contents.saves.length === 1 ? '' : 's'}
                                </span>
                            </div>
                            <span className="text-sm text-zinc-400">
                                {formatBytes(used)} used of {contents.size_mb} MB
                            </span>
                        </div>
                        <div className="h-1.5 w-full bg-zinc-900 rounded-full overflow-hidden">
                            <div
                                className="h-full bg-sky-600 rounded-full transition-all"
                                style={{ width: `${percent}%` }}
                            />
                        </div>
                    </div>
                )}

                {loading && (
                    <div className="flex items-center justify-center space-x-2 text-zinc-500 py-16">
                        <Loader2 size={18} className="animate-spin" />
                        <span>Reading the card...</span>
                    </div>
                )}

                {error && (
                    <div className="flex items-start space-x-2 bg-red-600/10 border border-red-600/30 text-red-400 rounded-lg p-3 text-sm">
                        <AlertTriangle size={18} className="shrink-0 mt-0.5" />
                        <span>{error}</span>
                    </div>
                )}

                {contents && contents.saves.length === 0 && (
                    <div className="text-center text-zinc-600 py-16">
                        <Save size={40} className="mx-auto mb-2 opacity-40" />
                        <p>This card has no saves on it yet.</p>
                        <p className="text-sm text-zinc-700 mt-1">
                            Play a game with this card assigned and its save will show up here.
                        </p>
                    </div>
                )}

                {contents && contents.saves.length > 0 && (
                    <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 gap-3">
                        {contents.saves.map((save) => (
                            <SaveCard key={save.folder} save={save} />
                        ))}
                    </div>
                )}

                <p className="text-xs text-zinc-600">
                    ISObe only reads this card. Saves can't be edited or deleted from here.
                </p>
            </div>
        </Modal>
    );
};

export default SaveBrowserModal;
