import React, { createContext, useCallback, useContext, useRef, useState } from 'react';
import Flashbar, { FlashbarProps } from '@cloudscape-design/components/flashbar';

interface FlashItem extends FlashbarProps.MessageDefinition {
  id: string;
}

interface FlashbarContextValue {
  addFlash: (item: Omit<FlashItem, 'id'> & { id?: string }) => string;
  removeFlash: (id: string) => void;
}

const FlashbarContext = createContext<FlashbarContextValue | null>(null);

export const useFlashbar = () => {
  const ctx = useContext(FlashbarContext);
  if (!ctx) throw new Error('useFlashbar must be used within FlashbarProvider');
  return ctx;
};

export const FlashbarProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [items, setItems] = useState<FlashItem[]>([]);
  const timers = useRef<Map<string, ReturnType<typeof setTimeout>>>(new Map());

  const removeFlash = useCallback((id: string) => {
    setItems((prev) => prev.filter((i) => i.id !== id));
    const timer = timers.current.get(id);
    if (timer) {
      clearTimeout(timer);
      timers.current.delete(id);
    }
  }, []);

  const addFlash = useCallback(
    (item: Omit<FlashItem, 'id'> & { id?: string }) => {
      const id = item.id ?? crypto.randomUUID();
      const flash: FlashItem = {
        ...item,
        id,
        dismissible: item.dismissible ?? true,
        onDismiss: () => removeFlash(id),
      };
      setItems((prev) => [flash, ...prev]);

      // Auto-dismiss after 8 seconds (longer to give time to click Undo)
      const timer = setTimeout(() => removeFlash(id), 8000);
      timers.current.set(id, timer);

      return id;
    },
    [removeFlash],
  );

  return (
    <FlashbarContext.Provider value={{ addFlash, removeFlash }}>
      {children}
      <div style={{ position: 'fixed', top: 56, right: 16, zIndex: 2000, maxWidth: 500 }}>
        <Flashbar items={items} />
      </div>
    </FlashbarContext.Provider>
  );
};
