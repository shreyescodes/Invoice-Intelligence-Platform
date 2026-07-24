import React from 'react';

interface CardProps {
  children: React.ReactNode;
  className?: string;
  noPadding?: boolean;
  style?: React.CSSProperties;
}

export const Card: React.FC<CardProps> = ({ children, className = '', noPadding = false, style }) => {
  return (
    <div className={`glass-panel card ${noPadding ? 'no-padding' : ''} ${className}`} style={style}>
      {children}
    </div>
  );
};
