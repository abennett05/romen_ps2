import React, { useState, useRef } from 'react';
import Modal from '../Modal';
import { Upload } from 'lucide-react';
import IconButton from '../IconButton';
import UploadList from '../UploadList';
import type { FileUploadItem } from '../../hooks/useGameUploads';

interface AddGameModalProps {
    isOpen: boolean;
    onClose: () => void;
    queue: FileUploadItem[];
    onUpload: (files: FileList | null) => void;
    // NEW: Add this so we can delete items
    onRemove: (fileName: string) => void; 
}

const AddGameModal: React.FC<AddGameModalProps> = ({ 
    isOpen, 
    onClose, 
    queue, 
    onUpload, 
    onRemove // Destructure it here
}) => {
    
    // React Hooks
    const [isDragging, setIsDragging] = useState(false);
    // Use a ref for the hidden file input
    const fileInputRef = useRef<HTMLInputElement>(null);

    // -- Event Handlers --

    const handleDragOver = (e: React.DragEvent) => {
        e.preventDefault();
        e.stopPropagation();
        setIsDragging(true);
    };

    const handleDragLeave = (e: React.DragEvent) => {
        e.preventDefault();
        e.stopPropagation();
        setIsDragging(false);
    };

    const handleDrop = (e: React.DragEvent) => {
        e.preventDefault();
        e.stopPropagation();
        setIsDragging(false);
        
        if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
            onUpload(e.dataTransfer.files);
        }
    };

    const triggerFileSelect = () => {
        fileInputRef.current?.click();
    };

    const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
        if (e.target.files && e.target.files.length > 0) {
            onUpload(e.target.files);
        }
    };

    // If queue is empty, we show the upload prompt. 
    // If queue has items, we show the list.
    const showUploadPrompt = queue.length === 0;

    return (
        <Modal isOpen={isOpen} onClose={onClose} title="Add To Library">
            {/* We wrap the content in a div that handles the drag events.
               We add a visual cue (border-sky-500) when dragging.
            */}
            <div 
                className={`transition-colors duration-200 rounded-xl p-4
                    ${isDragging ? 'bg-zinc-800/50 border-2 border-dashed border-sky-500' : ''}
                `}
                onDragOver={handleDragOver}
                onDragLeave={handleDragLeave}
                onDrop={handleDrop}
            >
                
                {showUploadPrompt ? (
                    <div className="flex flex-col items-center justify-center space-y-4 py-8 border-2 border-dashed border-zinc-700 rounded-xl hover:border-zinc-500 transition-colors">
                        
                        <div onClick={triggerFileSelect}>
                            <IconButton 
                                icon={<Upload size={32} className='text-white' />} 
                                bgColor="bg-sky-600 hover:bg-sky-500" 
                            />
                        </div>

                        <div className="text-center">
                            <p className="text-zinc-300 font-medium">Drag & Drop or Click to Upload</p>
                            <p className="text-sm text-zinc-500 mt-1">.ISO Format Only</p>
                        </div>

                        {/* Hidden Input */}
                        <input 
                            type="file" 
                            ref={fileInputRef} 
                            onChange={handleFileChange} 
                            className="hidden" 
                            accept=".iso, .ISO" 
                            multiple 
                        />
                    </div>
                ) : (
                    <div className="flex flex-col">
                        {/* The List of Active Uploads */}
                        <UploadList items={queue} onRemove={onRemove} />
                        
                        {/* Optional: Add more files button at bottom of list */}
                        <div className="mt-4 flex justify-end">
                            <button 
                                onClick={triggerFileSelect}
                                className="text-sm text-zinc-400 hover:text-white transition-colors flex items-center"
                            >
                                <Upload size={14} className="mr-2"/> Add Another
                            </button>
                             {/* Re-render input here so it's accessible even in list view */}
                             <input 
                                type="file" 
                                ref={fileInputRef} 
                                onChange={handleFileChange} 
                                className="hidden" 
                                accept=".iso, .ISO" 
                                multiple 
                            />
                        </div>
                    </div>
                )}
            </div>
        </Modal>
    );
}

export default AddGameModal;