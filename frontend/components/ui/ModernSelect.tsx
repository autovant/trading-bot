"use client";

import React, { useState, useRef, useEffect } from 'react';
import { ChevronDown, Check } from 'lucide-react';
import { cn } from '@/utils/cn';

export interface Option {
    value: string;
    label: string;
}

interface ModernSelectProps {
    value: string;
    onChange: (value: string) => void;
    options: Option[];
    label?: string;
    className?: string;
    placeholder?: string;
}

export const ModernSelect: React.FC<ModernSelectProps> = ({
    value,
    onChange,
    options,
    label,
    className,
    placeholder = "Select..."
}) => {
    const [isOpen, setIsOpen] = useState(false);
    const containerRef = useRef<HTMLDivElement>(null);

    const selectedOption = options.find(opt => opt.value === value);

    useEffect(() => {
        const handleClickOutside = (event: MouseEvent) => {
            if (containerRef.current && !containerRef.current.contains(event.target as Node)) {
                setIsOpen(false);
            }
        };

        document.addEventListener('mousedown', handleClickOutside);
        return () => document.removeEventListener('mousedown', handleClickOutside);
    }, []);

    return (
        <div className={cn("relative", className)} ref={containerRef}>
            {label && (
                <label className="block text-[10px] uppercase tracking-wider text-text-secondary font-bold mb-1.5 ml-1">
                    {label}
                </label>
            )}

            <button
                type="button"
                onClick={() => setIsOpen(!isOpen)}
                className={cn(
                    "w-full flex items-center justify-between px-3 py-2 text-sm text-left transition-all duration-200",
                    "bg-background-primary border border-white/10 rounded-lg",
                    "hover:border-white/20 hover:bg-background-secondary",
                    "focus:outline-none focus:ring-1 focus:ring-brand-secondary/50 focus:border-brand-secondary/50",
                    isOpen && "border-brand-secondary/50 ring-1 ring-brand-secondary/50"
                )}
            >
                <span className={cn(
                    "font-medium truncate",
                    !selectedOption ? "text-text-tertiary" : "text-text-primary"
                )}>
                    {selectedOption ? selectedOption.label : placeholder}
                </span>
                <ChevronDown className={cn(
                    "w-4 h-4 text-text-tertiary transition-transform duration-200",
                    isOpen && "transform rotate-180 text-brand-secondary"
                )} />
            </button>

            {isOpen && (
                <div className="absolute z-50 w-full mt-1 overflow-hidden bg-background-elevated border border-white/10 rounded-lg shadow-xl animate-in fade-in zoom-in-95 duration-100">
                    <div className="max-h-60 overflow-auto py-1 custom-scrollbar">
                        {options.map((option) => (
                            <button
                                key={option.value}
                                onClick={() => {
                                    onChange(option.value);
                                    setIsOpen(false);
                                }}
                                className={cn(
                                    "w-full flex items-center justify-between px-3 py-2 text-sm transition-colors",
                                    "hover:bg-white/5 hover:text-white",
                                    value === option.value ? "bg-brand-secondary/10 text-brand-secondary" : "text-text-secondary"
                                )}
                            >
                                <span className="font-medium">{option.label}</span>
                                {value === option.value && (
                                    <Check className="w-3.5 h-3.5 ml-2" />
                                )}
                            </button>
                        ))}
                    </div>
                </div>
            )}
        </div>
    );
};
