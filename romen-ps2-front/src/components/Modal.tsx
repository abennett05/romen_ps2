import { X } from 'lucide-react';
import React, { useEffect } from 'react';

// Define the shape of your props
interface ModalProps {
  isOpen: boolean;
  onClose: () => void; // A function that returns nothing
  title: string;
  children: React.ReactNode; // Allows passing JSX elements inside
}

const Modal: React.FC<ModalProps> = ({ isOpen, onClose, title, children }) => {
  useEffect(() => {
    if (isOpen) {
      document.body.style.overflow = 'hidden';
    } else {
      document.body.style.overflow = 'unset';
    }
  }, [isOpen]);

  if (!isOpen) return null;

  return (
    <div 
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm"
      onClick={onClose} 
    >
      <div 
        className="relative bg-zinc-900 border border-zinc-700 w-full max-w-md p-6 rounded-xl shadow-2xl animate-in fade-in zoom-in duration-200"
        onClick={(e: React.MouseEvent) => e.stopPropagation()} // Typed event
      >
        <div className="flex justify-between items-center mb-10">
            <h2 className="text-4xl font-bold text-white">{title}</h2>
            <button onClick={onClose} className="text-zinc-500 hover:text-white transition-colors">
                <X size={24} />
            </button>
        </div>
        <div className="text-zinc-300">
            {children}
        </div>
      </div>
    </div>
  );
}

export default Modal;