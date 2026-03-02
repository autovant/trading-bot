
import React, { useState, useRef, useEffect } from 'react';
import { Send, Sparkles, X, Activity, BrainCircuit, Target, TrendingUp, TrendingDown, AlertTriangle, ArrowUpCircle, ArrowDownCircle, MinusCircle } from 'lucide-react';
import { ChatMessage, TradeSuggestion, MarketAnalysis } from '@/types';
import { chatWithAi, analyzeMarketContext, generateTradeSuggestion } from '@/services/ai';
import { Card } from '@/components/ui/Card';
import { cn } from '@/lib/utils';

interface AIAssistantProps {
    isOpen: boolean;
    onClose: () => void;
    marketData: any; // Context to pass to AI
    onSuggestionReceived?: (suggestion: TradeSuggestion) => void;
}

const MarketAnalysisCard: React.FC<{ analysis: MarketAnalysis }> = ({ analysis }) => {
    const isBullish = analysis.sentiment === 'BULLISH';
    const isBearish = analysis.sentiment === 'BEARISH';

    let sentimentColor = 'text-text-tertiary';
    let SentimentIcon = MinusCircle;

    if (isBullish) {
        sentimentColor = 'text-accent-success';
        SentimentIcon = ArrowUpCircle;
    } else if (isBearish) {
        sentimentColor = 'text-accent-danger';
        SentimentIcon = ArrowDownCircle;
    }

    return (
        <div className="bg-background-elevated/30 border border-white/10 rounded-xl p-4 my-2 backdrop-blur-sm">
            <div className="flex justify-between items-start mb-3">
                <div className="flex items-center gap-2">
                    <SentimentIcon size={18} className={sentimentColor} />
                    <span className={cn("font-bold text-sm tracking-wider", sentimentColor)}>{analysis.sentiment}</span>
                </div>
                <div className="px-2 py-0.5 bg-white/5 rounded text-[10px] font-mono border border-white/5">
                    {analysis.symbol}
                </div>
            </div>

            <p className="text-sm text-text-secondary leading-relaxed mb-4">
                {analysis.summary}
            </p>

            <div className="grid grid-cols-2 gap-3 mb-3">
                <div className="bg-background-primary/50 rounded p-2 border-l-2 border-accent-success/50">
                    <div className="text-[10px] text-text-tertiary uppercase font-bold">Support</div>
                    <div className="font-mono text-sm text-white">{analysis.supportLevel.toLocaleString()}</div>
                </div>
                <div className="bg-background-primary/50 rounded p-2 border-l-2 border-accent-danger/50">
                    <div className="text-[10px] text-text-tertiary uppercase font-bold">Resistance</div>
                    <div className="font-mono text-sm text-white">{analysis.resistanceLevel.toLocaleString()}</div>
                </div>
            </div>

            <div className="flex items-center justify-between pt-2 border-t border-white/5">
                <div className="text-[10px] text-text-tertiary uppercase font-bold">Immediate Action</div>
                <div className={cn(
                    "text-xs font-bold px-3 py-1 rounded-full border",
                    analysis.signal === 'LONG' ? 'bg-accent-success/20 border-accent-success text-accent-success' :
                        analysis.signal === 'SHORT' ? 'bg-accent-danger/20 border-accent-danger text-accent-danger' :
                            'bg-accent-warning/20 border-accent-warning text-accent-warning'
                )}>
                    {analysis.signal} ({analysis.confidence}%)
                </div>
            </div>
        </div>
    );
};

const TradeSuggestionCard: React.FC<{ suggestion: TradeSuggestion }> = ({ suggestion }) => {
    const isLong = suggestion.direction === 'LONG';
    const isWait = suggestion.direction === 'WAIT';

    if (isWait) {
        return (
            <div className="bg-background-elevated/50 border border-white/5 rounded-xl p-4 my-2">
                <div className="flex items-center gap-2 mb-2">
                    <AlertTriangle size={16} className="text-accent-warning" />
                    <span className="font-bold text-accent-warning">Market Indecisive</span>
                </div>
                <p className="text-sm text-text-secondary">{suggestion.reasoning}</p>
            </div>
        );
    }

    const colorClass = isLong ? 'text-accent-success' : 'text-accent-danger';
    const bgClass = isLong ? 'bg-accent-success/10 border-accent-success/20' : 'bg-accent-danger/10 border-accent-danger/20';

    return (
        <div className={cn("rounded-xl border p-4 my-2", bgClass)}>
            <div className="flex justify-between items-start mb-3">
                <div className="flex items-center gap-2">
                    {isLong ? <TrendingUp size={18} className={colorClass} /> : <TrendingDown size={18} className={colorClass} />}
                    <span className={cn("font-bold text-lg", colorClass)}>{suggestion.direction} {suggestion.symbol}</span>
                </div>
                <div className="px-2 py-0.5 bg-background-primary/50 rounded text-xs font-mono text-text-secondary border border-white/5">
                    {suggestion.confidence}% Conf.
                </div>
            </div>

            <div className="grid grid-cols-2 gap-3 mb-3">
                <div className="bg-background-primary/30 rounded p-2">
                    <div className="text-[10px] text-text-tertiary uppercase">Entry</div>
                    <div className="font-mono text-sm text-text-primary">{suggestion.entryPrice.toLocaleString()}</div>
                </div>
                <div className="bg-background-primary/30 rounded p-2">
                    {/* Empty for spacing or could add R:R ratio */}
                    <div className="text-[10px] text-text-tertiary uppercase">R:R Ratio</div>
                    <div className="font-mono text-sm text-text-primary">1:2.5</div>
                </div>
                <div className="bg-background-primary/30 rounded p-2 border-l-2 border-accent-danger">
                    <div className="text-[10px] text-text-tertiary uppercase">Stop Loss</div>
                    <div className="font-mono text-sm text-text-primary">{suggestion.stopLoss.toLocaleString()}</div>
                </div>
                <div className="bg-background-primary/30 rounded p-2 border-l-2 border-accent-success">
                    <div className="text-[10px] text-text-tertiary uppercase">Take Profit</div>
                    <div className="font-mono text-sm text-text-primary">{suggestion.takeProfit.toLocaleString()}</div>
                </div>
            </div>

            <p className="text-xs text-text-secondary leading-relaxed border-t border-white/5 pt-2">
                <span className="font-semibold text-text-tertiary">Reasoning: </span>
                {suggestion.reasoning}
            </p>
        </div>
    );
};

export const AIAssistant: React.FC<AIAssistantProps> = ({ isOpen, onClose, marketData, onSuggestionReceived }) => {
    const [messages, setMessages] = useState<ChatMessage[]>([
        {
            id: 'init',
            role: 'ai',
            text: 'Cupertino Quant System online. I am monitoring the BTC-PERP order flow. How can I assist your execution today?',
            timestamp: new Date()
        }
    ]);
    const [input, setInput] = useState('');
    const [isTyping, setIsTyping] = useState(false);
    const scrollRef = useRef<HTMLDivElement>(null);

    useEffect(() => {
        if (scrollRef.current) {
            scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
        }
    }, [messages, isTyping]);

    const handleSend = async () => {
        if (!input.trim()) return;

        const userMsg: ChatMessage = {
            id: Date.now().toString(),
            role: 'user',
            text: input,
            timestamp: new Date()
        };

        setMessages(prev => [...prev, userMsg]);
        setInput('');
        setIsTyping(true);

        // Prepare context
        const contextStr = `Price: ${marketData.price}, Positions: ${marketData.positions?.length || 0}`;

        const aiResponseText = await chatWithAi(userMsg.text, contextStr);

        const aiMsg: ChatMessage = {
            id: (Date.now() + 1).toString(),
            role: 'ai',
            text: aiResponseText,
            timestamp: new Date()
        };

        setMessages(prev => [...prev, aiMsg]);
        setIsTyping(false);
    };

    const handleQuickAnalysis = async () => {
        setIsTyping(true);
        const analysis = await analyzeMarketContext(
            marketData.candles,
            marketData.positions,
            marketData.price,
            marketData.orderBook
        );

        if (analysis) {
            const aiMsg: ChatMessage = {
                id: Date.now().toString(),
                role: 'ai',
                text: "Here is the current market breakdown:",
                timestamp: new Date(),
                marketAnalysis: analysis
            };
            setMessages(prev => [...prev, aiMsg]);
        } else {
            const errorMsg: ChatMessage = {
                id: Date.now().toString(),
                role: 'ai',
                text: "Analysis currently unavailable due to data feed interruption.",
                timestamp: new Date()
            };
            setMessages(prev => [...prev, errorMsg]);
        }

        setIsTyping(false);
    };

    const handleGenerateSignal = async () => {
        setIsTyping(true);
        const suggestion = await generateTradeSuggestion(
            marketData.candles,
            marketData.price,
            marketData.orderBook
        );

        if (suggestion) {
            // Pass suggestion to parent to render on Chart
            if (onSuggestionReceived) {
                onSuggestionReceived(suggestion);
            }

            const aiMsg: ChatMessage = {
                id: Date.now().toString(),
                role: 'ai',
                text: "Based on the current market structure, here is a suggested setup:",
                timestamp: new Date(),
                tradeSuggestion: suggestion
            };
            setMessages(prev => [...prev, aiMsg]);
        } else {
            const aiMsg: ChatMessage = {
                id: Date.now().toString(),
                role: 'ai',
                text: "Market conditions are too volatile to generate a high-confidence signal right now.",
                timestamp: new Date()
            };
            setMessages(prev => [...prev, aiMsg]);
        }
        setIsTyping(false);
    };

    if (!isOpen) return null;

    return (
        <div className="fixed right-4 bottom-20 w-[400px] h-[600px] z-50 flex flex-col animate-fade-in">
            <div className="absolute inset-0 bg-background-tertiary/90 backdrop-blur-xl border border-white/10 rounded-2xl shadow-2xl flex flex-col overflow-hidden">
                {/* Header */}
                <div className="p-4 border-b border-white/5 flex items-center justify-between bg-white/5">
                    <div className="flex items-center gap-3">
                        <div className="w-8 h-8 rounded-full bg-gradient-to-tr from-accent-primary to-purple-600 flex items-center justify-center shadow-lg shadow-purple-500/20">
                            <Sparkles size={16} className="text-white" />
                        </div>
                        <div>
                            <h3 className="text-sm font-bold text-white">Cupertino AI</h3>
                            <div className="flex items-center gap-1.5">
                                <span className="w-1.5 h-1.5 rounded-full bg-accent-success animate-pulse"></span>
                                <span className="text-[10px] text-accent-success uppercase tracking-wider font-semibold">Live Connected</span>
                            </div>
                        </div>
                    </div>
                    <button onClick={onClose} className="p-2 hover:bg-white/10 rounded-full text-text-secondary transition-colors">
                        <X size={16} />
                    </button>
                </div>

                {/* Chat Area */}
                <div className="flex-1 overflow-y-auto p-4 space-y-4" ref={scrollRef}>
                    {messages.map((msg) => (
                        <div key={msg.id} className={cn("flex", msg.role === 'user' ? 'justify-end' : 'justify-start')}>
                            <div className={cn(
                                "max-w-[85%] rounded-2xl p-3 text-sm leading-relaxed",
                                msg.role === 'user'
                                    ? 'bg-accent-primary text-white rounded-br-none'
                                    : 'bg-background-elevated border border-white/5 text-text-secondary rounded-bl-none'
                            )}>
                                {msg.text.split('\n').map((line, i) => (
                                    <p key={i} className={i > 0 ? 'mt-1' : ''}>{line}</p>
                                ))}

                                {/* Render Market Analysis Card */}
                                {msg.marketAnalysis && (
                                    <MarketAnalysisCard analysis={msg.marketAnalysis} />
                                )}

                                {/* Render Trade Suggestion Card */}
                                {msg.tradeSuggestion && (
                                    <TradeSuggestionCard suggestion={msg.tradeSuggestion} />
                                )}

                                <div className={cn("text-[10px] mt-2 opacity-50", msg.role === 'user' ? 'text-white' : 'text-text-tertiary')}>
                                    {msg.timestamp.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                                </div>
                            </div>
                        </div>
                    ))}
                    {isTyping && (
                        <div className="flex justify-start">
                            <div className="bg-background-elevated border border-white/5 px-4 py-3 rounded-2xl rounded-bl-none flex gap-1">
                                <span className="w-1.5 h-1.5 bg-text-tertiary rounded-full animate-bounce"></span>
                                <span className="w-1.5 h-1.5 bg-text-tertiary rounded-full animate-bounce delay-75"></span>
                                <span className="w-1.5 h-1.5 bg-text-tertiary rounded-full animate-bounce delay-150"></span>
                            </div>
                        </div>
                    )}
                </div>

                {/* Quick Actions */}
                <div className="px-4 py-2 flex gap-2 overflow-x-auto no-scrollbar">
                    <button
                        onClick={handleQuickAnalysis}
                        className="flex items-center gap-2 px-3 py-1.5 bg-background-elevated border border-white/10 rounded-full text-xs text-text-secondary hover:text-white hover:border-accent-primary/50 transition-all whitespace-nowrap"
                    >
                        <Activity size={12} />
                        Analyze Market
                    </button>
                    <button
                        onClick={handleGenerateSignal}
                        className="flex items-center gap-2 px-3 py-1.5 bg-background-elevated border border-white/10 rounded-full text-xs text-text-secondary hover:text-white hover:border-accent-primary/50 transition-all whitespace-nowrap"
                    >
                        <Target size={12} />
                        Get Trade Setup
                    </button>
                    <button
                        onClick={() => setInput("What is the Order Book Imbalance suggesting?")}
                        className="flex items-center gap-2 px-3 py-1.5 bg-background-elevated border border-white/10 rounded-full text-xs text-text-secondary hover:text-white hover:border-accent-primary/50 transition-all whitespace-nowrap"
                    >
                        <BrainCircuit size={12} />
                        Check OBI
                    </button>
                </div>

                {/* Input */}
                <div className="p-4 border-t border-white/5 bg-background-secondary/50">
                    <div className="relative">
                        <input
                            type="text"
                            value={input}
                            onChange={(e) => setInput(e.target.value)}
                            onKeyDown={(e) => e.key === 'Enter' && handleSend()}
                            placeholder="Ask Cupertino Quant..."
                            className="w-full bg-background-primary border border-white/10 rounded-xl pl-4 pr-12 py-3 text-sm text-white placeholder:text-text-tertiary focus:outline-none focus:border-accent-primary/50 transition-colors"
                        />
                        <button
                            onClick={handleSend}
                            className="absolute right-2 top-2 p-1.5 bg-accent-primary rounded-lg text-white hover:bg-accent-primary/90 transition-colors"
                        >
                            <Send size={14} />
                        </button>
                    </div>
                </div>
            </div>
        </div>
    );
};
