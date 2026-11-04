import { createFileRoute, Link } from '@tanstack/react-router'
import {
  ActivityIcon,
  CheckIcon,
  ExternalLinkIcon,
  EyeIcon,
  EyeOffIcon,
  RotateCcwIcon,
  ScanSearchIcon,
  SparklesIcon,
} from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'
import { Field, Section } from '@/components/common/FormSection'
import { PageHeader } from '@/components/common/PageHeader'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { detectComfyUi, PROVIDER_META, testComfyConnection } from '@/services/aiGenerator'
import { useStudio } from '@/store/studioStore'

export const Route = createFileRoute('/settings')({
  staticData: { title: 'API 配置' },
  component: SettingsPage,
})

const COMFY_META = PROVIDER_META.comfyui

function SettingsPage() {
  const { apiConfig, updateProviderConfig } = useStudio()
  const [showKey, setShowKey] = useState(false)
  const [testingComfy, setTestingComfy] = useState(false)

  const pCfg = apiConfig.providers.comfyui

  const handleTestComfy = async () => {
    setTestingComfy(true)
    try {
      const info = await testComfyConnection(pCfg.baseUrl, pCfg.apiKey)
      toast.success(`连接成功：${info}`)
    } catch (e) {
      toast.error(e instanceof Error ? e.message : '连接失败', { duration: 10000 })
    } finally {
      setTestingComfy(false)
    }
  }

  const handleDetectComfy = async () => {
    setTestingComfy(true)
    try {
      const found = await detectComfyUi(pCfg.baseUrl, pCfg.apiKey)
      if (!found) {
        toast.error('未找到可用的 ComfyUI（已尝试当前地址、127.0.0.1:8000、127.0.0.1:8188），请确认已启动并检查跨域设置', {
          duration: 10000,
        })
        return
      }
      updateProviderConfig('comfyui', { baseUrl: found.baseUrl })
      toast.success(`已识别：${found.info}（${found.baseUrl}）`)
    } finally {
      setTestingComfy(false)
    }
  }

  return (
    <>
      <PageHeader
        title="API 接口配置"
        actions={
          <Button size="sm" asChild>
            <Link to="/studio">
              <SparklesIcon className="size-4" />
              返回合成台
            </Link>
          </Button>
        }
      />

      {/* 本地 ComfyUI 连接配置 */}
      <Section
        title={`${COMFY_META.name} 连接配置`}
        actions={
          <div className="flex items-center gap-1.5">
            <Button variant="outline" size="sm" onClick={handleDetectComfy} disabled={testingComfy}>
              <ScanSearchIcon className="size-3.5" />
              自动识别
            </Button>
            <Button variant="outline" size="sm" onClick={handleTestComfy} disabled={testingComfy}>
              <ActivityIcon className="size-3.5" />
              {testingComfy ? '检测中…' : '测试连接'}
            </Button>
            <Button variant="ghost" size="sm" asChild>
              <a href={COMFY_META.docUrl} target="_blank" rel="noreferrer">
                <ExternalLinkIcon className="size-3.5" />
                文档
              </a>
            </Button>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => {
                updateProviderConfig('comfyui', {
                  baseUrl: COMFY_META.defaultBaseUrl,
                  model: COMFY_META.models[0].value,
                })
                toast.success('已恢复默认')
              }}
            >
              <RotateCcwIcon className="size-3.5" />
              重置
            </Button>
          </div>
        }
      >
        <Field
          label="ComfyUI 地址 (Base URL)"
          hint={`本地运行本站时填 /comfy（同源代理，无需改跨域设置）；直连时 ComfyUI 需加启动参数 --enable-cors-header "${typeof window !== 'undefined' ? window.location.origin : '*'}"。Desktop 版默认端口 8000，便携版 8188`}
        >
          <Input
            type="text"
            value={pCfg.baseUrl}
            onChange={(e) => updateProviderConfig('comfyui', { baseUrl: e.target.value })}
            placeholder={COMFY_META.defaultBaseUrl}
          />
        </Field>

        <Field label="API Key（可选，本地留空）">
          <div className="relative">
            <Input
              type={showKey ? 'text' : 'password'}
              value={pCfg.apiKey}
              onChange={(e) => updateProviderConfig('comfyui', { apiKey: e.target.value })}
              placeholder="本地 ComfyUI 无需填写，远程鉴权可填 Token"
              className="pr-10"
            />
            <button
              type="button"
              onClick={() => setShowKey((s) => !s)}
              className="absolute top-1/2 right-3 -translate-y-1/2 text-muted-foreground hover:text-foreground"
            >
              {showKey ? <EyeOffIcon className="size-4" /> : <EyeIcon className="size-4" />}
            </button>
          </div>
        </Field>
      </Section>

      <p className="text-sm text-muted-foreground">模型由工作流决定。请返回合成台导入工作流，并设置人像、服装和姿势节点。</p>

      <div className="flex justify-end">
        <Button size="sm" onClick={() => toast.success('配置已保存')}>
          <CheckIcon className="size-4" />
          保存配置
        </Button>
      </div>
    </>
  )
}