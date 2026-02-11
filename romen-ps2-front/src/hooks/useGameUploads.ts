import { useState, useCallback } from 'react';
import axios from 'axios';

export type UploadStatus = 'pending' | 'uploading' | 'processing' | 'completed' | 'error';

export interface FileUploadItem {
    fileObject: File;
    progress: number;
    status: UploadStatus;
    displayTitle?: string;
    coverUrl?: string;
    // 1. Add this so we can kill the request later
    controller: AbortController; 
}

const wait = (ms: number) => new Promise(resolve => setTimeout(resolve, ms));

export const useGameUploads = () => {
    const [queue, setQueue] = useState<FileUploadItem[]>([]);

    // Helper to update item state
    const updateItem = (fileName: string, update: Partial<FileUploadItem>) => {
        setQueue(prev => prev.map(item => 
            item.fileObject.name === fileName ? { ...item, ...update } : item
        ));
    };

    const processFile = async (file: File, controller: AbortController) => {
        const formData = new FormData();
        formData.append("file", file);

        try {
            updateItem(file.name, { status: 'uploading', progress: 0 });

            // 2. Pass the signal to the upload request
            const { data } = await axios.post("http://localhost:8000/upload", formData, {
                signal: controller.signal, // <--- This connects the abort button
                onUploadProgress: (e) => {
                    const total = e.total || file.size;
                    const percent = Math.round((e.loaded * 100) / total);
                    if (percent === 100) {
                        updateItem(file.name, { progress: 100, status: 'processing' });
                    } else {
                        updateItem(file.name, { progress: percent, status: 'uploading' });
                    }
                }
            });

            // PHASE 2: POLLING
            while (true) {
                // Check if user clicked trash during the wait
                if (controller.signal.aborted) throw new Error("Cancelled by user");
                
                await wait(1000); 

                // Check again before network request
                if (controller.signal.aborted) throw new Error("Cancelled by user");

                // 3. Pass signal here too, so we can cancel polling requests!
                const job = await axios.get(`http://localhost:8000/job/${data.job_id}`, {
                    signal: controller.signal
                });

                if (job.data.status === "completed" || job.data.status === "success") {
                    updateItem(file.name, { 
                        status: 'completed', 
                        displayTitle: job.data.title, 
                        coverUrl: job.data.cover_url 
                    });
                    break; 
                }
                
                if (job.data.status === "error") {
                    updateItem(file.name, { status: 'error' });
                    break;
                }
            }

        } catch (error) {
            // 4. Handle Cancellation cleanly
            if (axios.isCancel(error) || (error as Error).message === "Cancelled by user") {
                console.log(`Upload ${file.name} cancelled.`);
                // We don't need to set status to error, because we are about to remove it from the queue entirely
            } else {
                console.error(error);
                updateItem(file.name, { status: 'error', progress: 0 });
            }
        }
    };

    const uploadFiles = useCallback((files: FileList | null) => {
        if (!files) return;
        
        const newItems = Array.from(files).map(f => {
            // 5. Create a controller for each file
            const controller = new AbortController();
            
            // Trigger the process
            processFile(f, controller);

            return { 
                fileObject: f, 
                progress: 0, 
                status: 'pending',
                controller: controller 
            } as FileUploadItem;
        });
        
        setQueue(prev => [...prev, ...newItems]);
    }, []);

    // 6. The Removal Function
    const removeFile = useCallback((fileName: string) => {
        setQueue(prev => {
            // Find the item to cancel
            const itemToRemove = prev.find(i => i.fileObject.name === fileName);
            
            if (itemToRemove) {
                // ABORT THE REQUEST (Stops network activity)
                itemToRemove.controller.abort();
            }

            // Remove from UI
            return prev.filter(i => i.fileObject.name !== fileName);
        });
    }, []);

    // 7. Clear Completed (For re-opening modal)
    const clearCompleted = useCallback(() => {
        setQueue(prev => prev.filter(i => i.status !== 'completed'));
    }, []);

    return { queue, uploadFiles, removeFile, clearCompleted };
};