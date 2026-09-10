import React from 'react';

interface CardProps {
  children: React.ReactNode;
  noPadding?: boolean;
  className?: string;
}

export const Card: React.FC<CardProps> = ({ children, noPadding, className = '' }) => {
  return (
    <div className={`ios-glass rounded-3xl overflow-hidden ${noPadding ? '' : 'p-6'} ${className}`}>
      {children}
    </div>
  );
};
