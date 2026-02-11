import React from 'react';

const IconButton : React.FC<{ icon?: React.ReactNode, bgColor?: string, onClick?: () => void }> = ({ icon, bgColor = "bg-sky-500", onClick }) => {
    return (
        <>
            <div className={`w-auto h-auto p-5 ${bgColor} rounded-full flex items-center justify-center hover:opacity-80 active:scale-95 cursor-pointer transition-all`} onClick={onClick}>
                {icon}
            </div>
        </>
    );
 }
export default IconButton;