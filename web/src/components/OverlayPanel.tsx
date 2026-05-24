import React from 'react';
import { AnimatePresence, motion } from 'framer-motion';
import './OverlayPanel.css';

interface Props {
  open: boolean;
  onClose: () => void;
  children: React.ReactNode;
}

/**
 * Slide-in side drawer that sits on top of the bubble canvas. Tapping the
 * darkened backdrop closes it. Right-anchored to align with TabRail.
 */
export const OverlayPanel: React.FC<Props> = ({ open, onClose, children }) => {
  return (
    <AnimatePresence>
      {open && (
        <>
          <motion.div
            key="backdrop"
            className="overlay-panel__backdrop"
            onClick={onClose}
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.2 }}
          />
          <motion.aside
            key="drawer"
            className="overlay-panel"
            initial={{ x: '110%', opacity: 0 }}
            animate={{ x: 0, opacity: 1 }}
            exit={{ x: '110%', opacity: 0 }}
            transition={{ type: 'spring', stiffness: 280, damping: 30 }}
          >
            <button
              className="overlay-panel__close"
              onClick={onClose}
              aria-label="close panel"
            >
              ×
            </button>
            <div className="overlay-panel__body">{children}</div>
          </motion.aside>
        </>
      )}
    </AnimatePresence>
  );
};
