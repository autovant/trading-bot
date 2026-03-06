import React from 'react';
import { clsx, type ClassValue } from 'clsx';
import { twMerge } from 'tailwind-merge';

export function cn(...inputs: ClassValue[]) {
    return twMerge(clsx(inputs));
}

interface GlassCardProps extends React.HTMLAttributes<HTMLDivElement> {
    hoverEffect?: boolean;
}

export const GlassCard: React.FC<GlassCardProps> = ({
    children,
    className,
    hoverEffect = false,
    ...props
}) => {
    return (
        <div
            className={cn(
                "glass-panel p-6 flex flex-col gap-4",
                hoverEffect && "glass-panel-hover",
                className
            )}
            {...props}
        >
            {children}
        </div>
    );
};
