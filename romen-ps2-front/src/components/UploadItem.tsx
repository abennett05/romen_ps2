import React from 'react';
import IconButton from './IconButton';
import { Trash, CheckCircle, AlertCircle, Loader2 } from 'lucide-react';
import type { UploadStatus } from '../hooks/useGameUploads';

// 1. Update the interface to accept progress data
interface UploadItemProps {
    title: string;
    coverUrl?: string;
    progress: number; // 0 to 100
    status: UploadStatus
    onTrash?: () => void;
}

const UploadItem: React.FC<UploadItemProps> = ({ title, coverUrl, progress, status, onTrash }) => {
    
    // Helper to determine bar color based on status
    const getBarColor = () => {
        if (status === 'error') return 'bg-red-500';
        if (status === 'completed') return 'bg-green-500';
        return 'bg-sky-500';
    };

    return (
        <div className="bg-zinc-800 p-4 rounded-lg shadow-md mb-3">
            <div className="flex flex-row space-x-4 items-center mb-3">
                {/* Placeholder Image */}
                <div className="w-16 h-24 bg-zinc-700 rounded-md shrink-0 overflow-hidden">
                    <img className="w-full h-full object-cover opacity-100" src={coverUrl} alt={title} />
                </div>

                <div className="grow min-w-0">
                    <p className="text-lg font-semibold text-zinc-100 truncate">{title}</p>
                    
                    {/* Status Text Logic */}
                    <div className="flex items-center space-x-2 text-sm mt-1">
                        {status === 'completed' ? (
                            <span className="text-green-400 flex items-center">
                                <CheckCircle size={14} className="mr-1"/> Complete
                            </span>
                        ) : status === 'error' ? (
                            <span className="text-red-400 flex items-center">
                                <AlertCircle size={14} className="mr-1"/> Failed
                            </span>
                        ) : status === 'processing' ? (
                            <span className="text-amber-400 flex items-center">
                                <Loader2 size={14} className="mr-1 animate-spin"/> Processing...
                            </span>
                        ) : (
                            <span className="text-zinc-400">
                                {status === 'pending' ? 'Waiting...' : `Uploading ${progress}%`}
                            </span>
                        )}
                    </div>
                </div>

                {/* Trash Button (Only show if not complete/uploading to prevent accidents, or always show if you prefer) */}
                <div className="ml-auto hover:text-red-500 transition-colors duration-200" onClick={onTrash}>
                    <IconButton icon={<Trash size={24}/>} bgColor="hover:bg-zinc-700"/>
                </div>
            </div>
            
            {/* --- THE PROGRESS BAR --- */}
            <div className="w-full bg-zinc-900 rounded-full h-2 overflow-hidden">
                <div 
                    className={`h-full transition-all duration-300 ease-out ${getBarColor()}`}
                    style={{ width: `${progress}%` }}
                />
            </div>
        </div>
    );
}

export default UploadItem;