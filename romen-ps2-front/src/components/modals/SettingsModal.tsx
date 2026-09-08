import Modal from '../Modal';
import React, { useState, useEffect } from 'react';
import IconButton from '../IconButton';
import { Trash, HardDrive, FolderSearch, Wrench, MemoryStick } from 'lucide-react';
import type { StorageDevice } from '../../App';
import UpdateNotice from '../UpdateNotice';
import axios from 'axios';

// 1. Add the update callback to the interface
interface SettingsModalProps {
    isOpen: boolean;
    onClose: () => void;
    device?: StorageDevice | null; // Allow null to match usage
    onUpdatePath?: (newPath: string) => Promise<boolean>;
    onRefresh?: () => void; 
}

const SettingsModal: React.FC<SettingsModalProps> = ({ isOpen, onClose, device, onUpdatePath, onRefresh }) => {
    const deviceConnected = device != null;

    // 2. Local state to handle user typing
    const [localPath, setLocalPath] = useState(device?.path || "");

    // VMC preferences, loaded from the server so they survive a restart.
    const [autoProvision, setAutoProvision] = useState(false);
    const [vmcSize, setVmcSize] = useState(8);
    const [vmcSizes, setVmcSizes] = useState<number[]>([8, 16, 32, 64]);

    // 3. Sync local state when the device prop changes (e.g. initial load)
    useEffect(() => {
        setLocalPath(device?.path || "");
    }, [device]);

    useEffect(() => {
        if (isOpen && onRefresh) {
            onRefresh();
        }
    }, [isOpen]);

    useEffect(() => {
        if (!isOpen) return;
        axios.get('/settings/vmc')
            .then(({ data }) => {
                setAutoProvision(!!data.auto_provision);
                setVmcSize(data.default_size_mb ?? 8);
                if (data.sizes) setVmcSizes(data.sizes);
            })
            .catch((error) => console.error("Failed to fetch VMC settings: ", error));
    }, [isOpen]);

    const saveVmcSettings = async (next: { auto_provision?: boolean; default_size_mb?: number }) => {
        try {
            const { data } = await axios.post('/settings/vmc', next);
            if (data.status !== "success") {
                alert(data.message ?? "Failed to save memory card settings.");
                return false;
            }
            return true;
        } catch (error) {
            console.error(error);
            alert("Failed to reach server.");
            return false;
        }
    };

    const handleAutoProvisionChange = async (value: boolean) => {
        setAutoProvision(value);
        if (!await saveVmcSettings({ auto_provision: value })) setAutoProvision(!value);
    };

    const handleVmcSizeChange = async (value: number) => {
        const previous = vmcSize;
        setVmcSize(value);
        if (!await saveVmcSettings({ default_size_mb: value })) setVmcSize(previous);
    };

    // 4. The "Commit" function - fires when user is done
    const handleCommit = async () => {
        // Only fire if the path actually changed and isn't empty
        if (localPath !== device?.path) {
            console.log("Committing new path:", localPath);
            if (onUpdatePath) {
                const success = await onUpdatePath(localPath);
                if (!success) {
                    setLocalPath(device?.path || "");
                }
            }
        } else {
            setLocalPath(device?.path || "");
        }
    };

    const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
        if (e.key === 'Enter') {
            e.currentTarget.blur(); // Remove focus, which triggers onBlur -> handleCommit
        }
    };

    // --- Helpers ---
    function PrettyPrintSize(bytes: number) {
        return `${(bytes / (1024 ** 3)).toFixed(1)} GB`
    }

    function ColorByPercentage(numerator: number, denominator: number) {
        if (!denominator) return 'text-zinc-400';
        const percent = (numerator / denominator);
        if (percent >= 0.75) return 'text-green-400'; // High free space
        if (percent >= 0.30) return 'text-amber-200'; // Medium
        return 'text-red-400'; // Low space
    }

    async function OnDeleteClick() {
        if (!confirm("Are you sure you want to clear the library?\nThis Action CANNOT be Undone.")) return;
        const response = await axios.delete(`/library/clear`);

        if (response.data.success) {
            alert("Library has been cleared successfully.")
        } else {
            alert("Unable to clear library, if issue persists rebuild library.")
        }
    }

    async function OnRebuildClick() {
        if (!confirm("Are you sure you want to rebuild the library?\nThis action may take some time depending on the size of your library.")) return;
        const response = await axios.post('/rebuild-library', null);
        alert(response.data.message);
    }

    return (
        <Modal isOpen={isOpen} onClose={onClose} title="Settings">
            <div className="flex flex-col space-y-5">
                {/* Header Section */}
                <div className="flex flex-row items-center space-x-4">
                    <div className={`p-2 rounded-full ${deviceConnected ? 'bg-zinc-800' : 'bg-red-900/20'}`}>
                        <HardDrive size={48} className={deviceConnected ? "text-white" : "text-red-400"} />
                    </div>
                    <div className="overflow-hidden">
                        <h3 className="font-bold text-2xl text-zinc-100 truncate" title={device?.label}>
                            {device?.label || "No Device"}
                        </h3>
                    </div>
                </div>

                {/* Status Details */}
                <div className="pl-2">
                    <p className="text-zinc-400 font-semibold">
                        Status: <span className={`${deviceConnected ? "text-green-400" : "text-red-400"} font-normal`}>
                            {deviceConnected ? "Connected" : "Disconnected"}
                        </span>
                    </p>
                    <p className="text-zinc-400 font-semibold">
                        Space: <span className={`${ColorByPercentage(device?.space_free ?? 0, device?.total_space ?? 1)} font-normal`}>
                            {PrettyPrintSize(device?.space_free ?? 0)} / {PrettyPrintSize(device?.total_space ?? 0)}
                        </span>
                    </p>
                </div>

                <div className="border-t border-zinc-700 my-2" />

                {/* Actions */}
                <div className="flex flex-col space-y-2">
                    <div className="flex flex-row items-center space-x-4">
                        <FolderSearch size={24} className="text-white" />
                        <p className="font-semibold text-xl text-zinc-100">Device Path</p>
                    </div>
                    
                    {/* EDITABLE INPUT */}
                    <input 
                        className='w-full bg-zinc-800 border-2 border-zinc-600 focus:border-sky-500 text-zinc-100 rounded-xl p-2 transition-colors outline-none' 
                        type='text' 
                        value={localPath} 
                        onChange={(e) => setLocalPath(e.target.value)} // Just updates state
                        onBlur={handleCommit} // Fires when clicking away
                        onKeyDown={handleKeyDown} // Fires on Enter
                        placeholder="/path/to/library"
                    />
                </div>
                {/* ACTIONS */}
                <div className={`${deviceConnected ? 'flex' : 'hidden'}`}>
                    <div className="flex flex-row items-center space-x-4 mt-4">
                        <IconButton icon={<Wrench size={32} className="text-white" />} bgColor="bg-amber-600  hover:bg-amber-500" onClick={OnRebuildClick} />
                        <p className="font-semibold text-xl text-zinc-100">Rebuild Library</p>
                    </div>

                    <div className="flex flex-row items-center space-x-4 mt-4">
                        <IconButton icon={<Trash size={32} className="text-white" />} bgColor="bg-red-600 hover:bg-red-500" onClick={OnDeleteClick} />
                        <p className="font-semibold text-xl text-zinc-100">Clear Library</p>
                    </div>
                </div>

                <div className="border-t border-zinc-700 my-2" />

                {/* MEMORY CARDS */}
                <div className="flex flex-col space-y-3">
                    <div className="flex flex-row items-center space-x-4">
                        <MemoryStick size={24} className="text-white" />
                        <p className="font-semibold text-xl text-zinc-100">Memory Cards</p>
                    </div>

                    <label className="flex items-center space-x-3 cursor-pointer pl-1">
                        <input
                            type="checkbox"
                            checked={autoProvision}
                            onChange={(e) => handleAutoProvisionChange(e.target.checked)}
                            className="w-5 h-5 accent-sky-600 cursor-pointer"
                        />
                        <span className="text-zinc-300">Give every new game its own card</span>
                    </label>

                    <div className={`flex items-center space-x-3 pl-1 ${autoProvision ? '' : 'opacity-40 pointer-events-none'}`}>
                        <span className="text-zinc-400 text-sm">Card size</span>
                        <select
                            value={vmcSize}
                            onChange={(e) => handleVmcSizeChange(Number(e.target.value))}
                            className="bg-zinc-800 border border-zinc-700 focus:border-sky-500 text-zinc-200 text-sm rounded-md p-1.5 outline-none"
                        >
                            {vmcSizes.map((size) => (
                                <option key={size} value={size}>{size} MB</option>
                            ))}
                        </select>
                    </div>

                    <p className="text-xs text-zinc-600 pl-1">
                        Cards are created when a game is added and assigned to slot 1.
                        Existing cards are never overwritten.
                    </p>
                </div>

                <div className="border-t border-zinc-700 my-2" />

                {/* UPDATES */}
                <UpdateNotice active={isOpen} />
            </div>
        </Modal>
    );
}

export default SettingsModal;