'use client';

import { useEffect, useRef, useState } from 'react';
import { X, LoaderCircle, Check } from 'lucide-react';

type Model = { id: string; name: string; provider: string };
type Provider = { label: string; base_url: string; secrets: Record<string, boolean> };
type Settings = { models: Record<string, string>; choices: Record<string, Model[]>; providers: Record<string, Provider>; env_overrides: string[] };
const tasks: Record<string, string> = { llm: '剧本与拆分镜', vlm: '读图与水墨特征', image_t2i: '首张分镜图片', image_it2i: '继承参考图生成', video_first_frame: '首帧视频', video_start_end: '首尾帧视频', video_reference: '角色／场景参考视频' };
const secretLabels: Record<string, string> = { api_key: 'API Key', access_key: 'Access Key', secret_key: 'Secret Key' };
async function settingsRequest(method = 'GET', body?: unknown): Promise<Settings> {
  const response = await fetch('/api/ink/settings', { method, cache: 'no-store', credentials: 'same-origin', ...(body ? { headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) } : {}) });
  const data = await response.json();
  if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : '设置请求失败');
  return data;
}

export default function ApiSettings({ onClose, onSaved, busy }: { onClose: () => void; onSaved: () => Promise<void>; busy: boolean }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [settings, setSettings] = useState<Settings | null>(null);
  const [models, setModels] = useState<Record<string, string>>({});
  const [urls, setUrls] = useState<Record<string, string>>({});
  const [secrets, setSecrets] = useState<Record<string, Record<string, string>>>({});
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [saved, setSaved] = useState(false);
  useEffect(() => {
    const element = dialog.current;
    element?.showModal();
    let active = true;
    void settingsRequest().then(data => {
      if (!active) return;
      setSettings(data); setModels(data.models);
      setUrls(Object.fromEntries(Object.entries(data.providers).map(([key, value]) => [key, value.base_url])));
    }).catch(e => { if (active) setError(e instanceof Error ? e.message : '无法读取设置'); });
    return () => { active = false; element?.close(); };
  }, []);
  const locked = (path: string) => Boolean(settings?.env_overrides.includes(path));
  const used = new Set(Object.entries(models).map(([key, id]) => settings?.choices[key]?.find(m => m.id === id)?.provider).filter(Boolean));
  const save = async () => {
    if (!settings) return;
    setSaving(true); setError(''); setSaved(false);
    try {
      const providerUpdates: Record<string, Record<string, string>> = {};
      for (const [key, provider] of Object.entries(settings.providers)) {
        const values: Record<string, string> = {};
        if (urls[key] !== provider.base_url && !locked(`api_providers.${key}.base_url`)) values.base_url = urls[key].trim();
        for (const [field, value] of Object.entries(secrets[key] || {})) if (value.trim() && !locked(`api_providers.${key}.${field}`)) values[field] = value.trim();
        if (Object.keys(values).length) providerUpdates[key] = values;
      }
      const changedModels = Object.fromEntries(Object.entries(models).filter(([key, value]) => value !== settings.models[key] && !locked(`models.${key}`)));
      const result = await settingsRequest('PUT', { models: changedModels, providers: providerUpdates });
      setSettings(result); setModels(result.models); setSecrets({});
      setUrls(Object.fromEntries(Object.entries(result.providers).map(([key, value]) => [key, value.base_url])));
      setSaved(true);
      await onSaved();
    } catch (e) { setError(e instanceof Error ? e.message : '保存失败'); }
    finally { setSaving(false); }
  };
  return <dialog ref={dialog} className="ink-api-dialog" aria-labelledby="ink-api-title" onCancel={e => { e.preventDefault(); if (!saving) onClose(); }} onClick={e => { if (e.target === e.currentTarget && !saving) onClose(); }}>
    <div className="ink-api-panel">
      <header className="ink-api-heading"><div><h2 id="ink-api-title">模型与 API 设置</h2><p>设置用于本机水墨创作的所有项目，保存后立即生效。</p></div><button type="button" className="ink-icon-button" disabled={saving} onClick={onClose} aria-label="关闭设置"><X size={19} /></button></header>
      <form onSubmit={e => { e.preventDefault(); void save(); }}>
        <div className="ink-api-body">
          {error ? <p role="alert" className="ink-api-error">{error}</p> : null}
          {!settings && !error ? <p className="ink-api-loading"><LoaderCircle size={16} className="ink-job-spinner" />正在读取设置…</p> : null}
          {settings ? <>
            <section className="ink-api-section"><h3>1. 选择各步骤模型</h3><div className="ink-api-model-grid">{Object.entries(tasks).map(([key, label]) => {
              const selected = settings.choices[key]?.find(m => m.id === models[key]);
              const provider = selected ? settings.providers[selected.provider] : undefined;
              return <label key={key} className="ink-api-field">{label}<select value={models[key]} disabled={saving || locked(`models.${key}`)} onChange={e => { setModels({ ...models, [key]: e.target.value }); setSaved(false); }}>
                {!selected ? <option value={models[key]}>{models[key]}（请重新选择）</option> : null}
                {Object.entries(settings.providers).map(([id, p]) => { const choices = settings.choices[key]?.filter(m => m.provider === id) || []; return choices.length ? <optgroup key={id} label={p.label}>{choices.map(m => <option key={m.id} value={m.id}>{m.name}</option>)}</optgroup> : null; })}
              </select><span className="ink-api-field-note">{locked(`models.${key}`) ? '由启动环境指定' : provider ? `${provider.label} · ${Object.values(provider.secrets).every(Boolean) ? '密钥已配置' : '请在下方填写密钥'}` : '当前模型未注册或不支持本步骤'}</span></label>;
            })}</div><p className="ink-api-help">DeepSeek 可用于剧本与拆分镜；读图、图片和视频需分别选择支持对应能力的模型。配音沿用预设音色，无需在此填密钥。</p></section>
            <section className="ink-api-section"><h3>2. 填写服务商 API</h3><p className="ink-api-help">密钥保存在本机，不回显已有值。输入新密钥可替换，留空保留原值。</p><div className="ink-api-providers">{Object.entries(settings.providers).map(([key, provider]) => <details className="ink-api-provider" key={key} open={used.has(key)}><summary>{provider.label}{used.has(key) ? <span>当前选用</span> : null}</summary><div className="ink-api-provider-fields">
              <label className="ink-api-field">接口地址<input type="url" value={urls[key] || ''} disabled={saving || locked(`api_providers.${key}.base_url`)} onChange={e => { setUrls({ ...urls, [key]: e.target.value }); setSaved(false); }} placeholder="https://…" autoComplete="off" /></label>
              {Object.entries(provider.secrets).map(([field, configured]) => <label key={field} className="ink-api-field">{secretLabels[field] || field}<input type="password" value={secrets[key]?.[field] || ''} disabled={saving || locked(`api_providers.${key}.${field}`)} onChange={e => { setSecrets({ ...secrets, [key]: { ...secrets[key], [field]: e.target.value } }); setSaved(false); }} placeholder={configured ? '已配置 · 留空保留' : '粘贴此服务商的密钥'} autoComplete="new-password" spellCheck={false} /><span className="ink-api-field-note">{locked(`api_providers.${key}.${field}`) ? '由启动环境指定' : configured ? '已有密钥已隐藏' : '尚未配置'}</span></label>)}
            </div></details>)}</div></section>
          </> : null}
        </div>
        <footer className="ink-api-footer"><p role="status">{busy ? '生成任务进行中，完成后可保存设置。' : saved ? <><Check size={15} />已保存并生效；尚未验证服务商连接。</> : '保存不会调用模型，也不会产生生成费用。'}</p><button type="submit" className="ink-primary-button" disabled={!settings || saving || busy}>{saving ? '正在保存…' : '保存设置'}</button></footer>
      </form>
    </div>
  </dialog>;
}
