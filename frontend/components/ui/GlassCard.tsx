import React from 'react';
import { cn } from '@/utils/cn'; // Assuming utils/cn exists, standard in most next/shadcn setups

interface GlassCardProps extends React.HTMLAttributes<HTMLDivElement> {
    children: React.ReactNode;
    className?: string;
    variant?: 'default' | 'neo' | 'ghost';
    intensity?: 'low' | 'medium' | 'high';
    interactive?: boolean;
}

export const GlassCard = React.forwardRef<HTMLDivElement, GlassCardProps>(
    ({ children, className, variant = 'default', intensity = 'medium', interactive = false, ...props }, ref) => {

        const intensityStyles = {
            low: 'bg-background/40 backdrop-blur-sm border-white/5',
            medium: 'bg-background/60 backdrop-blur-md border-white/10',
            high: 'bg-background/80 backdrop-blur-lg border-white/20'
        };

        const variantStyles = {
            default: 'border shadow-xl',
            neo: 'border-t border-l border-white/10 shadow-[4px_4px_10px_0px_rgba(0,0,0,0.3)] bg-gradient-to-br from-white/5 to-transparent',
            ghost: 'border-none bg-transparent shadow-none'
        };

        return (
            <div
                ref={ref}
                className={cn(
                    'rounded-xl relative overflow-hidden transition-all duration-300',
                    intensityStyles[intensity],
                    variantStyles[variant],
                    interactive && 'hover:bg-white/5 hover:scale-[1.01] hover:shadow-2xl cursor-pointer',
                    className
                )}
                {...props}
            >
                {/* Noise texture overlay (optional, for grit) */}
                <div className="absolute inset-0 opacity-[0.03] pointer-events-none bg-[url('/noise.png')]" />

                <div className="relative z-10">
                    {children}
                </div>
            </div>
        );
    }
);

GlassCard.displayName = 'GlassCard';
