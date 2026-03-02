"use client";

import React from 'react';
import { cn } from "@/lib/utils";

interface CardProps extends React.HTMLAttributes<HTMLDivElement> {
    children: React.ReactNode;
    className?: string;
    noPadding?: boolean;
}

export const Card: React.FC<CardProps> = ({ children, className, noPadding = false, ...props }) => {
    return (
        <div className={cn("glass-card", className)} {...props}>
            <div className={noPadding ? '' : 'p-5'}>
                {children}
            </div>
        </div>
    );
};
