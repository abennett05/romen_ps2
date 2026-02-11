// UploadList.tsx
import type { FileUploadItem } from "../hooks/useGameUploads";
import UploadItem from "./UploadItem";
import React from "react";

interface UploadListProps {
    items: FileUploadItem[];
    onRemove: (name : string) => void;
}

const UploadList : React.FC<UploadListProps> = ({items, onRemove}) => {
    return (
        <div className="flex flex-col space-y-2 overflow-y-scroll max-h-80">
            {
                items.map((item) => (
                    <UploadItem 
                        key={item.fileObject.name} 
                        title={item.displayTitle || item.fileObject.name} 
                        coverUrl={item.coverUrl || "/img/placeholder_cover.jpg"}
                        progress={item.progress}
                        status={item.status}
                        onTrash={() => onRemove(item.fileObject.name)}
                    />
                ))
            }
        </div>
    );
}

export default UploadList;