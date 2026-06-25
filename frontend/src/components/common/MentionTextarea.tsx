import React, { useRef, useState, useCallback, useEffect } from 'react';
import { users as usersApi } from '@/api';
import type { User } from '@/types';

interface MentionTextareaProps {
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  rows?: number;
  disabled?: boolean;
}

const MentionTextarea: React.FC<MentionTextareaProps> = ({
  value,
  onChange,
  placeholder = 'Enter a note... Use @name to mention a user.',
  rows = 3,
  disabled = false,
}) => {
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const [dropdownOpen, setDropdownOpen] = useState(false);
  const [dropdownUsers, setDropdownUsers] = useState<User[]>([]);
  const [mentionStart, setMentionStart] = useState<number | null>(null);
  const [activeIdx, setActiveIdx] = useState(0);

  const closeDropdown = () => {
    setDropdownOpen(false);
    setMentionStart(null);
    setDropdownUsers([]);
    setActiveIdx(0);
  };

  const handleSelect = useCallback(
    (user: User) => {
      if (mentionStart === null) return;
      const before = value.slice(0, mentionStart);
      const cursorPos = textareaRef.current?.selectionStart ?? value.length;
      const after = value.slice(cursorPos);
      const inserted = `@${user.display_name} `;
      const newValue = before + inserted + after;
      onChange(newValue);
      closeDropdown();
      // Restore focus and set cursor
      requestAnimationFrame(() => {
        if (textareaRef.current) {
          const pos = mentionStart + inserted.length;
          textareaRef.current.focus();
          textareaRef.current.setSelectionRange(pos, pos);
        }
      });
    },
    [mentionStart, value, onChange],
  );

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (!dropdownOpen) return;
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setActiveIdx((i) => Math.min(i + 1, dropdownUsers.length - 1));
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setActiveIdx((i) => Math.max(i - 1, 0));
    } else if (e.key === 'Enter' || e.key === 'Tab') {
      if (dropdownUsers.length > 0) {
        e.preventDefault();
        handleSelect(dropdownUsers[activeIdx]);
      }
    } else if (e.key === 'Escape') {
      closeDropdown();
    }
  };

  const handleChange = async (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    const newVal = e.target.value;
    onChange(newVal);

    const cursor = e.target.selectionStart;
    // Detect if we're in a @mention: look back from cursor for @ with no spaces
    const textBeforeCursor = newVal.slice(0, cursor);
    const atMatch = textBeforeCursor.match(/@(\w*)$/);

    if (atMatch) {
      const token = atMatch[1];
      const start = cursor - token.length - 1; // position of @
      setMentionStart(start);
      try {
        const res = await usersApi.list({ search: token, page_size: 10 });
        const matched = res.data.items.filter(
          (u) => u.is_active && u.display_name.toLowerCase().includes(token.toLowerCase()),
        );
        if (matched.length > 0) {
          setDropdownUsers(matched);
          setActiveIdx(0);
          setDropdownOpen(true);
        } else {
          closeDropdown();
        }
      } catch {
        closeDropdown();
      }
    } else {
      closeDropdown();
    }
  };

  // Render @mention tokens highlighted in the note display (we just style the textarea here)
  return (
    <div style={{ position: 'relative' }}>
      <textarea
        ref={textareaRef}
        value={value}
        onChange={handleChange}
        onKeyDown={handleKeyDown}
        onBlur={(e) => {
          // Delay so click on dropdown option registers first
          if (!e.relatedTarget || !(e.relatedTarget as HTMLElement).dataset.mentionOption) {
            setTimeout(closeDropdown, 150);
          }
        }}
        rows={rows}
        disabled={disabled}
        placeholder={placeholder}
        style={{
          width: '100%',
          padding: '8px 12px',
          borderRadius: '8px',
          border: '2px solid var(--color-border-input-default, #7d8998)',
          fontSize: '14px',
          fontFamily: 'inherit',
          lineHeight: '1.5',
          resize: 'vertical',
          backgroundColor: 'var(--color-background-input-default, #fff)',
          color: 'var(--color-text-body-default, #0f141a)',
          boxSizing: 'border-box',
          outline: 'none',
        }}
        onFocus={(e) => {
          e.target.style.borderColor = 'var(--color-border-input-focused, #0972d3)';
        }}
      />
      {dropdownOpen && dropdownUsers.length > 0 && (
        <div
          style={{
            position: 'absolute',
            top: '100%',
            left: 0,
            right: 0,
            background: 'var(--color-background-container-content, #fff)',
            border: '1px solid var(--color-border-divider-default, #e9ebed)',
            borderRadius: '8px',
            boxShadow: '0 4px 12px rgba(0,0,0,0.15)',
            zIndex: 1000,
            maxHeight: '200px',
            overflowY: 'auto',
          }}
        >
          {dropdownUsers.map((u, i) => (
            <div
              key={u.id}
              data-mention-option="true"
              tabIndex={-1}
              onMouseDown={(e) => {
                e.preventDefault();
                handleSelect(u);
              }}
              style={{
                padding: '8px 12px',
                cursor: 'pointer',
                background: i === activeIdx ? 'var(--color-background-item-selected, #e6f2ff)' : 'transparent',
                fontSize: '14px',
              }}
            >
              <strong>{u.display_name}</strong>
              {u.email && (
                <span style={{ color: '#687078', marginLeft: '8px', fontSize: '12px' }}>{u.email}</span>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
};

export default MentionTextarea;
