import { createFileRoute, Link } from '@tanstack/react-router'
import { ActivityIcon, RotateCcwIcon, ScanSearchIcon, SparklesIcon } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'
import { Field, Section } from '@/components/common/FormSection'
import { PageHeader } from '@/components/common/PageHeader'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { detectComfyUi, PROVIDER_META, testComfyConnection } from '@/services/aiGenerator'
import { useStudio } from '@/store/studioStore'

export const Route = createFileRoute('/settings')({
  staticData: { title: 'ComfyUI 连接' },
  component: SettingsPage,
})

const COMFY_META = PROVIDER_META.comfyui

function SettingsPage() {
  const { apiConfig, updateProviderConfig } = useStudio()
  const [testingComfy, setTestingComfy] = useState(false)

  const pCfg = apiConfig.providers.comfyui

  const handleTestComfy = async () => {
    setTestingComfy(true)
    try {
      const info = await testComfyConnection(pCfg.baseUrl)
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
      const found = await detectComfyUi(pCfg.baseUrl)
      if (!found) {
        toast.error('未找到可用的 ComfyUI（已尝试当前地址、127.0.0.1:8000、127.0.0.1:8188），请确认本机 ComfyUI 已启动。', {
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

  const handleReset = () => {
    updateProviderConfig('comfyui', {
      baseUrl: COMFY_META.defaultBaseUrl,
      model: COMFY_META.models[0].value,
      // 清除历史版本遗留的 API Key；当前 UI 不再提供该字段，仅保留配置结构兼容。
      apiKey: '',
    })
    toast.success('已恢复默认')
  }

  return (
    <>
      <PageHeader
        title="ComfyUI 连接"
        description="本地单人使用，仅连接本机 ComfyUI；修改即时生效，无需手动保存。"
        actions={
          <Button size="sm" asChild>
            <Link to="/studio">
              <SparklesIcon className="size-4" />
              返回合成台
            </Link>
          </Button>
        }
      />

      {/* 本机 ComfyUI 连接配置 */}
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
            <Button variant="ghost" size="sm" onClick={handleReset}>
              <RotateCcwIcon className="size-3.5" />
              重置
            </Button>
          </div>
        }
      >
        <Field
          label="ComfyUI 地址 (Base URL)"
          hint="本地默认走同源代理 /comfy；直连可填 http://127.0.0.1:8000（Desktop 版）或 8188（便携版）。"
        >
          <Input
            type="text"
            value={pCfg.baseUrl}
            onChange={(e) => updateProviderConfig('comfyui', { baseUrl: e.target.value })}
            placeholder={COMFY_META.defaultBaseUrl}
          />
        </Field>
      </Section>

      <p className="text-sm text-muted-foreground">
        修改即时生效，无需手动保存。模型由工作流决定，请返回合成台导入工作流并设置人像、服装和姿势节点。
      </p>
    </>
  )
}