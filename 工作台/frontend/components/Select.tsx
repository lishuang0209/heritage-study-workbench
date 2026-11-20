'use client';

import {
  Children, Fragment, isValidElement, useCallback, useId, useLayoutEffect, useRef, useState,
  type ChangeEvent, type ComponentPropsWithoutRef, type KeyboardEvent, type ReactNode,
} from 'react';
import { createPortal } from 'react-dom';
import { Check, ChevronDown } from 'lucide-react';
import './select.css';

type Option = { value: string; label: string; disabled: boolean; index: number };
type Section = { label?: string; options: Option[] };
type SelectProps = Omit<ComponentPropsWithoutRef<'select'>, 'multiple' | 'size' | 'value' | 'defaultValue'> & {
  value?: string | number;
  defaultValue?: string | number;
};

function optionChildren(children: ReactNode): ReactNode[] {
  return Children.toArray(children).flatMap(child =>
    isValidElement<{ children?: ReactNode }>(child) && child.type === Fragment
      ? optionChildren(child.props.children)
      : [child],
  );
}

function readOptions(children: ReactNode) {
  const sections: Section[] = [];
  const options: Option[] = [];

  function addOption(node: ReactNode, section: Section, groupDisabled = false) {
    if (!isValidElement<ComponentPropsWithoutRef<'option'>>(node) || node.type !== 'option') return;
    const { children, value, label, disabled, hidden } = node.props;
    if (hidden) return;
    const text = optionChildren(children).filter(part => typeof part === 'string' || typeof part === 'number').join('').replace(/\s+/g, ' ').trim();
    const option = {
      label: label ?? text,
      value: value == null ? text : String(value),
      disabled: Boolean(disabled || groupDisabled),
      index: options.length,
    };
    options.push(option);
    section.options.push(option);
  }

  optionChildren(children).forEach(node => {
    if (isValidElement<ComponentPropsWithoutRef<'optgroup'>>(node) && node.type === 'optgroup') {
      const section: Section = { label: node.props.label, options: [] };
      optionChildren(node.props.children).forEach(child => addOption(child, section, node.props.disabled));
      if (section.options.length) sections.push(section);
    } else {
      const last = sections.at(-1);
      const section: Section = last && last.label === undefined ? last : { options: [] };
      addOption(node, section);
      if (section !== last && section.options.length) sections.push(section);
    }
  });
  return { options, sections };
}

export default function Select({
  children, id, className, style, value, defaultValue, disabled, required, title,
  form, name, tabIndex, onChange, onInvalid, 'aria-label': ariaLabel,
  'aria-labelledby': labelledBy, 'aria-describedby': describedBy, 'aria-invalid': ariaInvalid,
  ...nativeProps
}: SelectProps) {
  const uid = useId();
  const triggerId = id ?? `${uid}-trigger`;
  const listId = `${uid}-list`;
  const trigger = useRef<HTMLButtonElement>(null);
  const backing = useRef<HTMLSelectElement>(null);
  const popup = useRef<HTMLDivElement>(null);
  const typeahead = useRef({ text: '', time: 0 });
  const [host, setHost] = useState<HTMLElement | null>(null);
  const [opened, setOpened] = useState(false);
  const [activeIndex, setActiveIndex] = useState(-1);
  const [uncontrolledValue, setUncontrolledValue] = useState(() => defaultValue == null ? undefined : String(defaultValue));
  const [invalid, setInvalid] = useState(false);
  const { options, sections } = readOptions(children);
  const enabled = options.filter(option => !option.disabled);
  const currentValue = value == null ? uncontrolledValue : String(value);
  const selected = options.find(option => option.value === currentValue) ?? enabled[0] ?? options[0];
  const open = opened && !disabled && options.length > 0;
  const active = options[activeIndex]?.disabled ? undefined : options[activeIndex];
  const optionId = (index: number) => `${listId}-${index}`;

  const attachTrigger = useCallback((node: HTMLButtonElement | null) => {
    trigger.current = node;
    if (node) setHost(node.closest('form') ?? node.closest('dialog') ?? node.closest('main') ?? node.ownerDocument.body);
  }, []);

  function close() {
    setOpened(false);
    typeahead.current = { text: '', time: 0 };
  }

  function expand(option = enabled.find(item => item.index === selected?.index) ?? enabled[0]) {
    if (!options.length) return;
    setActiveIndex(option?.index ?? -1);
    setOpened(true);
  }

  function commit(option: Option | undefined) {
    close();
    const field = backing.current;
    if (!option || option.disabled || !field || trigger.current?.matches(':disabled')) return;
    if (field.value !== option.value) {
      field.value = option.value;
      field.dispatchEvent(new Event('change', { bubbles: true }));
    }
  }

  function change(event: ChangeEvent<HTMLSelectElement>) {
    if (value == null) setUncontrolledValue(event.target.value);
    setInvalid(false);
    onChange?.(event);
  }

  function keyDown(event: KeyboardEvent<HTMLButtonElement>) {
    if (event.nativeEvent.isComposing || event.ctrlKey || event.metaKey) return;
    const { key, altKey } = event;
    if (open && (key === 'Escape' || (altKey && key === 'ArrowUp'))) {
      event.preventDefault();
      event.stopPropagation();
      close();
      return;
    }
    if (open && key === 'Tab') {
      commit(active);
      return;
    }
    if (key === 'Enter' || key === ' ') {
      event.preventDefault();
      if (open) commit(active);
      else expand();
      return;
    }
    if (key === 'ArrowDown' || key === 'ArrowUp' || key === 'Home' || key === 'End') {
      event.preventDefault();
      if (key === 'Home') expand(enabled[0]);
      else if (key === 'End') expand(enabled.at(-1));
      else if (!open) expand(key === 'ArrowUp' ? enabled[0] : undefined);
      else if (!altKey) {
        const index = enabled.findIndex(option => option.index === activeIndex);
        const offset = key === 'ArrowDown' ? 1 : -1;
        expand(enabled[Math.max(0, Math.min(enabled.length - 1, index + offset))]);
      }
      return;
    }
    if (altKey || key.length !== 1 || !enabled.length) return;

    const now = event.timeStamp;
    const next = key.toLocaleLowerCase();
    const previous = now - typeahead.current.time < 600 ? typeahead.current.text : '';
    const cycling = previous === next;
    const search = cycling ? next : previous + next;
    const start = cycling ? enabled.findIndex(option => option.index === activeIndex) + 1 : 0;
    const order = [...enabled.slice(start), ...enabled.slice(0, start)];
    const match = order.find(option => option.label.toLocaleLowerCase().startsWith(search));
    typeahead.current = { text: search, time: now };
    if (match) {
      event.preventDefault();
      expand(match);
    }
  }

  useLayoutEffect(() => {
    const button = trigger.current;
    const list = popup.current;
    if (!open || !button || !list) return;
    const viewport = window.visualViewport;
    const inset = 8;
    const gap = 4;
    const maxHeight = 320;
    let frame = 0;

    list.showPopover?.();

    function position() {
      if (!button || !list) return;
      const rect = button.getBoundingClientRect();
      const left = viewport?.offsetLeft ?? 0;
      const top = viewport?.offsetTop ?? 0;
      const width = viewport?.width ?? document.documentElement.clientWidth;
      const height = viewport?.height ?? document.documentElement.clientHeight;
      if (rect.bottom <= top || rect.top >= top + height || !rect.width || button.matches(':disabled')) {
        close();
        return;
      }
      const panelWidth = Math.min(Math.max(rect.width, 192), width - inset * 2);
      const panelLeft = Math.max(left + inset, Math.min(rect.left, left + width - inset - panelWidth));
      list.style.width = `${panelWidth}px`;
      list.style.left = `${panelLeft}px`;
      const below = top + height - rect.bottom - gap - inset;
      const above = rect.top - top - gap - inset;
      const desired = Math.min(maxHeight, list.scrollHeight + 2);
      const opensUp = below < desired && above > below;
      list.style.maxHeight = `${Math.max(0, Math.min(maxHeight, opensUp ? above : below))}px`;
      const panelTop = opensUp ? rect.top - gap - list.offsetHeight : rect.bottom + gap;
      list.style.top = `${Math.max(top + inset, panelTop)}px`;
    }

    function schedulePosition() {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(position);
    }

    function dismissOutside(event: Event) {
      if (event.target instanceof Node && !list?.contains(event.target) && !button?.contains(event.target)) close();
    }

    position();
    const resize = new ResizeObserver(schedulePosition);
    resize.observe(button);
    resize.observe(list);
    document.addEventListener('pointerdown', dismissOutside, true);
    document.addEventListener('focusin', dismissOutside, true);
    window.addEventListener('resize', schedulePosition);
    window.addEventListener('scroll', schedulePosition, { capture: true, passive: true });
    viewport?.addEventListener('resize', schedulePosition);
    viewport?.addEventListener('scroll', schedulePosition);
    return () => {
      cancelAnimationFrame(frame);
      resize.disconnect();
      document.removeEventListener('pointerdown', dismissOutside, true);
      document.removeEventListener('focusin', dismissOutside, true);
      window.removeEventListener('resize', schedulePosition);
      window.removeEventListener('scroll', schedulePosition, true);
      viewport?.removeEventListener('resize', schedulePosition);
      viewport?.removeEventListener('scroll', schedulePosition);
      if (list.hidePopover && list.isConnected) list.hidePopover();
    };
  }, [open]);

  useLayoutEffect(() => {
    const list = popup.current;
    if (!open || !list || activeIndex < 0) return;
    const item = document.getElementById(`${listId}-${activeIndex}`);
    if (!item) return;
    const visible = list.getBoundingClientRect();
    const bounds = item.getBoundingClientRect();
    if (bounds.top < visible.top + 4) list.scrollTop -= visible.top + 4 - bounds.top;
    else if (bounds.bottom > visible.bottom - 4) list.scrollTop += bounds.bottom - visible.bottom + 4;
  }, [open, activeIndex, listId]);

  const errorId = `${uid}-invalid`;
  const showError = invalid && required && !selected?.value;
  return <>
    <button
      ref={attachTrigger} id={triggerId} type="button" role="combobox" className={`app-select-trigger${className ? ` ${className}` : ''}`}
      disabled={disabled} title={title ?? selected?.label} style={style} tabIndex={tabIndex}
      aria-label={ariaLabel} aria-labelledby={labelledBy} aria-required={required}
      aria-expanded={open} aria-controls={open ? listId : undefined}
      aria-activedescendant={open && active ? optionId(active.index) : undefined}
      aria-describedby={showError ? [describedBy, errorId].filter(Boolean).join(' ') : describedBy}
      aria-invalid={showError || ariaInvalid} onKeyDown={keyDown}
      onClick={() => { if (open) close(); else expand(); }}
    >
      <span className="app-select-value">{selected?.label || '请选择'}</span>
      <ChevronDown className="app-select-chevron" aria-hidden="true" size={16} strokeWidth={1.6} />
    </button>
    {showError ? <span id={errorId} className="app-select-error" aria-hidden="true">请选择一项。</span> : null}
    {host ? createPortal(
      <select
        {...nativeProps} ref={backing} hidden aria-hidden="true" tabIndex={-1} form={form} name={name}
        disabled={disabled} required={required} value={value} defaultValue={defaultValue} onChange={change}
        onInvalid={event => {
          onInvalid?.(event);
          event.preventDefault();
          setInvalid(true);
          trigger.current?.focus();
        }}
      >{children}</select>, host
    ) : null}
    {open && host ? createPortal(
      <div
        ref={popup} id={listId} className="app-select-list" popover="manual" role="listbox"
        aria-labelledby={labelledBy ?? (ariaLabel ? undefined : triggerId)} aria-label={ariaLabel}
      >
        {sections.map((section, index) => (
          <div key={index} role={section.label ? 'group' : 'presentation'} aria-label={section.label} className="app-select-group">
            {section.label ? <div className="app-select-group-label" aria-hidden="true">{section.label}</div> : null}
            {section.options.map(option => (
              <div
                key={option.index} id={optionId(option.index)} role="option"
                aria-selected={selected?.index === option.index} aria-disabled={option.disabled || undefined}
                className="app-select-option" data-active={active?.index === option.index || undefined}
                onMouseDown={event => event.preventDefault()}
                onClick={() => { if (!option.disabled) { trigger.current?.focus({ preventScroll: true }); commit(option); } }}
              >
                <span>{option.label}</span>
                {selected?.index === option.index ? <Check size={15} strokeWidth={1.8} aria-hidden="true" /> : null}
              </div>
            ))}
          </div>
        ))}
      </div>, host
    ) : null}
  </>;
}
