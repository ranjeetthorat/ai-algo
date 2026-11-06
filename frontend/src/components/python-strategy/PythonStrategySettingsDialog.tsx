import { AlertTriangle, Loader2 } from 'lucide-react'
import { useEffect, useState } from 'react'
import { pythonStrategyApi } from '@/api/python-strategy'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Separator } from '@/components/ui/separator'
import { Switch } from '@/components/ui/switch'
import type {
  PythonStrategy,
  StrategyParamField,
  StrategyParamValue,
  StrategySettings,
} from '@/types/python-strategy'
import { showToast } from '@/utils/toast'

interface PythonStrategySettingsDialogProps {
  strategy: PythonStrategy | null
  open: boolean
  onOpenChange: (open: boolean) => void
}

/** Pull the server's own message out of an axios error, which carries the reason a setting was refused. */
function errorMessage(error: unknown, fallback: string): string {
  const message = (error as { response?: { data?: { message?: unknown } } })?.response?.data
    ?.message
  return typeof message === 'string' && message ? message : fallback
}

/** Choice options can be numbers; the select works in strings, so map back to the declared value. */
function choiceValue(field: StrategyParamField, selected: string): StrategyParamValue {
  return field.options?.find((option) => String(option) === selected) ?? selected
}

function SettingInput({
  field,
  value,
  onChange,
}: {
  field: StrategyParamField
  value: StrategyParamValue
  onChange: (value: StrategyParamValue) => void
}) {
  const id = `setting-${field.name}`
  if (field.type === 'bool') {
    return (
      <Switch id={id} checked={value === true} onCheckedChange={(checked) => onChange(checked)} />
    )
  }
  if (field.type === 'choice') {
    return (
      <Select
        value={String(value)}
        onValueChange={(selected) => onChange(choiceValue(field, selected))}
      >
        <SelectTrigger id={id} className="w-full">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {(field.options ?? []).map((option) => (
            <SelectItem key={String(option)} value={String(option)}>
              {String(option)}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    )
  }
  const numeric = field.type === 'int' || field.type === 'float'
  return (
    <Input
      id={id}
      type={numeric ? 'number' : 'text'}
      inputMode={field.type === 'int' ? 'numeric' : numeric ? 'decimal' : undefined}
      step={field.type === 'int' ? 1 : numeric ? 'any' : undefined}
      min={field.min}
      max={field.max}
      value={String(value)}
      onChange={(event) => onChange(event.target.value)}
    />
  )
}

function rangeHint(field: StrategyParamField): string | null {
  if (field.min !== undefined && field.max !== undefined) return `${field.min} to ${field.max}`
  if (field.min !== undefined) return `at least ${field.min}`
  if (field.max !== undefined) return `at most ${field.max}`
  return null
}

export function PythonStrategySettingsDialog({
  strategy,
  open,
  onOpenChange,
}: PythonStrategySettingsDialogProps) {
  const [settings, setSettings] = useState<StrategySettings | null>(null)
  const [values, setValues] = useState<Record<string, StrategyParamValue>>({})
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [formError, setFormError] = useState<string | null>(null)
  const [confirmClear, setConfirmClear] = useState(false)
  const [clearing, setClearing] = useState(false)

  const strategyId = strategy?.id

  useEffect(() => {
    if (!open || !strategyId) return
    let cancelled = false
    setLoading(true)
    setSettings(null)
    setFormError(null)
    setConfirmClear(false)
    pythonStrategyApi
      .getSettings(strategyId)
      .then((data) => {
        if (cancelled) return
        setSettings(data)
        setValues(Object.fromEntries(data.fields.map((field) => [field.name, field.value])))
      })
      .catch((error) => {
        if (!cancelled) setFormError(errorMessage(error, 'Could not load the strategy settings.'))
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [open, strategyId])

  const handleSave = async () => {
    if (!strategyId) return
    setSaving(true)
    setFormError(null)
    try {
      const response = await pythonStrategyApi.saveSettings(strategyId, values)
      showToast.success(response.message || 'Settings saved', 'pythonStrategy')
      onOpenChange(false)
    } catch (error) {
      setFormError(errorMessage(error, 'Could not save the settings.'))
    } finally {
      setSaving(false)
    }
  }

  const handleClearState = async () => {
    if (!strategyId) return
    setClearing(true)
    try {
      const response = await pythonStrategyApi.clearSavedState(strategyId)
      showToast.success(response.message || 'Saved state cleared', 'pythonStrategy')
      setSettings((current) => (current ? { ...current, saved_state: null } : current))
      setConfirmClear(false)
    } catch (error) {
      showToast.error(errorMessage(error, 'Could not clear the saved state.'), 'pythonStrategy')
    } finally {
      setClearing(false)
    }
  }

  const fields = settings?.fields ?? []
  const savedState = settings?.saved_state
  const running = settings?.is_running ?? strategy?.status === 'running'

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>Settings: {strategy?.name}</DialogTitle>
          <DialogDescription>Changes apply the next time the strategy starts.</DialogDescription>
        </DialogHeader>

        {loading && (
          <div className="flex items-center justify-center py-8 text-muted-foreground">
            <Loader2 className="h-5 w-5 animate-spin" />
          </div>
        )}

        {!loading && settings?.error && (
          <Alert variant="destructive">
            <AlertTriangle className="h-4 w-4" />
            <AlertDescription className="text-xs">{settings.error}</AlertDescription>
          </Alert>
        )}

        {!loading && settings && !settings.error && fields.length === 0 && (
          <p className="text-sm text-muted-foreground">
            This strategy declares no settings. Add a <code className="font-mono">PARAMS</code>{' '}
            block at the top of the script to get a form here.
          </p>
        )}

        {!loading && settings && settings.problems.length > 0 && (
          <Alert>
            <AlertTriangle className="h-4 w-4" />
            <AlertDescription className="text-xs">
              {settings.problems.join(' ')} The default is shown instead.
            </AlertDescription>
          </Alert>
        )}

        {!loading && fields.length > 0 && (
          <div className="space-y-4">
            {fields.map((field) => {
              const hint = rangeHint(field)
              return (
                <div key={field.name} className="space-y-1.5">
                  <div className="flex items-center justify-between gap-2">
                    <Label htmlFor={`setting-${field.name}`}>{field.label || field.name}</Label>
                    {field.type === 'bool' && (
                      <SettingInput
                        field={field}
                        value={values[field.name]}
                        onChange={(value) => setValues((v) => ({ ...v, [field.name]: value }))}
                      />
                    )}
                  </div>
                  {field.type !== 'bool' && (
                    <SettingInput
                      field={field}
                      value={values[field.name] ?? ''}
                      onChange={(value) => setValues((v) => ({ ...v, [field.name]: value }))}
                    />
                  )}
                  <p className="text-xs text-muted-foreground">
                    {field.help ? `${field.help} ` : ''}
                    Default {String(field.default)}
                    {hint ? `, ${hint}` : ''}.
                  </p>
                </div>
              )
            })}
          </div>
        )}

        {formError && (
          <Alert variant="destructive">
            <AlertTriangle className="h-4 w-4" />
            <AlertDescription className="text-xs">{formError}</AlertDescription>
          </Alert>
        )}

        {!loading && settings && (
          <>
            <Separator />
            <div className="space-y-2">
              <p className="text-sm font-medium">Saved state</p>
              <p className="text-xs text-muted-foreground">
                {!savedState
                  ? 'No saved state. The next start is a fresh start.'
                  : savedState.damaged
                    ? 'The saved state file is damaged. Check the positions at the broker, then clear it.'
                    : `Saved on ${savedState.date ?? 'an unknown date'}: ${
                        savedState.open_positions ?? 0
                      } open position(s) recorded${
                        savedState.pending_orders
                          ? `, ${savedState.pending_orders} order(s) with an unknown outcome`
                          : ''
                      }. On its next start the strategy continues from it only if the broker's positions match.`}
              </p>
              {savedState && !confirmClear && (
                <Button
                  variant="outline"
                  size="sm"
                  disabled={running}
                  onClick={() => setConfirmClear(true)}
                >
                  Clear saved state
                </Button>
              )}
              {savedState && running && (
                <p className="text-xs text-muted-foreground">
                  Stop the strategy to clear its saved state.
                </p>
              )}
              {confirmClear && (
                <div className="rounded border border-destructive/40 bg-destructive/5 p-3 space-y-2">
                  <p className="text-xs">
                    The next start will be a fresh start and will not continue any position this
                    strategy holds. Handle open positions at the broker first.
                  </p>
                  <div className="flex gap-2">
                    <Button
                      variant="destructive"
                      size="sm"
                      disabled={clearing}
                      onClick={handleClearState}
                    >
                      {clearing && <Loader2 className="h-4 w-4 mr-2 animate-spin" />}
                      Yes, clear it
                    </Button>
                    <Button variant="outline" size="sm" onClick={() => setConfirmClear(false)}>
                      Keep it
                    </Button>
                  </div>
                </div>
              )}
            </div>
          </>
        )}

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Close
          </Button>
          {fields.length > 0 && !settings?.error && (
            <Button onClick={handleSave} disabled={saving || loading}>
              {saving && <Loader2 className="h-4 w-4 mr-2 animate-spin" />}
              Save settings
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
