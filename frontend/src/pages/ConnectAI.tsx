import { AlertCircle, Bot, Check, Copy, Eye, EyeOff, Info, Plug } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Link } from 'react-router'
import { BRAND } from '@/brand/brand'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { showToast } from '@/utils/toast'

interface ConnectConfig {
  mcp_enabled: boolean
  apikey_auth_enabled: boolean
  mcp_url: string
  has_api_key: boolean
  api_key: string | null
  orders_enabled: boolean
}

// The MCP clients we tell the user about. The config block is the same for all;
// only where it goes differs, so each row is just a name and that location.
const CLIENTS: { name: string; location: string }[] = [
  {
    name: 'Claude Desktop',
    location:
      'Settings → Developer → Edit Config (claude_desktop_config.json), or add it from the MCP settings.',
  },
  { name: 'Cursor', location: 'Settings → MCP → Add new MCP server (or ~/.cursor/mcp.json).' },
  { name: 'VS Code', location: 'Command palette → "MCP: Add Server", or a .vscode/mcp.json file.' },
  { name: 'Antigravity', location: 'Settings → MCP → add a server.' },
]

function configBlock(url: string, apiKey: string): string {
  return JSON.stringify(
    {
      mcpServers: {
        fastalgo: {
          url,
          headers: { Authorization: `Bearer ${apiKey}` },
        },
      },
    },
    null,
    2
  )
}

async function copy(text: string, label: string) {
  try {
    await navigator.clipboard.writeText(text)
    showToast.success(`${label} copied to clipboard`, 'clipboard')
  } catch {
    showToast.error(`Could not copy ${label}`, 'clipboard')
  }
}

export default function ConnectAI() {
  const [config, setConfig] = useState<ConnectConfig | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [showKey, setShowKey] = useState(false)

  useEffect(() => {
    ;(async () => {
      try {
        const res = await fetch('/connect-ai/config', {
          credentials: 'include',
          headers: { Accept: 'application/json' },
        })
        if (res.ok) {
          setConfig(await res.json())
        } else {
          showToast.error('Could not load the connection details', 'system')
        }
      } catch {
        showToast.error('Could not load the connection details', 'system')
      } finally {
        setIsLoading(false)
      }
    })()
  }, [])

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-16">
        <div className="h-8 w-8 animate-spin rounded-full border-b-2 border-primary"></div>
      </div>
    )
  }

  const name = BRAND.displayName
  const url = config?.mcp_url ?? ''
  const apiKey = config?.api_key ?? ''
  const maskedKey = apiKey ? `${apiKey.slice(0, 6)}${'•'.repeat(24)}${apiKey.slice(-4)}` : ''
  const authHeader = apiKey ? `Bearer ${apiKey}` : ''
  const block = url && apiKey ? configBlock(url, showKey ? apiKey : maskedKey) : ''
  const blockForCopy = url && apiKey ? configBlock(url, apiKey) : ''

  return (
    <div className="py-6 max-w-3xl mx-auto space-y-6">
      <div>
        <h1 className="flex items-center gap-2 text-2xl font-semibold">
          <Plug className="h-6 w-6" />
          Connect your AI
        </h1>
        <p className="text-muted-foreground mt-1">
          Use your own AI (Claude Desktop, Cursor, VS Code, Antigravity, …) with {name}. It can
          explain the platform, read your account, and write strategies you upload and run. No extra
          account or API key from a provider — you use the AI you already have.
        </p>
      </div>

      {!config?.mcp_enabled && (
        <Alert className="border-yellow-500 bg-yellow-500/10">
          <AlertCircle className="h-4 w-4" />
          <AlertDescription>
            Remote MCP is turned off, so an AI client cannot connect yet. Enable it by setting{' '}
            <code className="font-mono">MCP_HTTP_ENABLED=true</code> and{' '}
            <code className="font-mono">MCP_PUBLIC_URL</code> in your <code>.env</code> (or re-run
            the installer and choose "Enable Remote MCP"), then restart {name}. The steps below are
            what you will use once it is on.
          </AlertDescription>
        </Alert>
      )}

      {!config?.apikey_auth_enabled && (
        <Alert className="border-yellow-500 bg-yellow-500/10">
          <AlertCircle className="h-4 w-4" />
          <AlertDescription>
            API-key sign-in for MCP is disabled on this server (
            <code className="font-mono">MCP_APIKEY_AUTH_ENABLED=false</code>), so the pasted token
            below will not be accepted. Your client would need to use OAuth sign-in instead.
          </AlertDescription>
        </Alert>
      )}

      {/* Step 1: pick and install a client */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Bot className="h-5 w-5" />
            1. Open your AI client
          </CardTitle>
          <CardDescription>
            Any MCP-capable AI works. If you do not have one, Claude Desktop is the simplest to
            start with. Open its MCP settings, then come back for the block below.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <ul className="space-y-2 text-sm">
            {CLIENTS.map((c) => (
              <li key={c.name} className="flex flex-col sm:flex-row sm:gap-2">
                <span className="font-medium shrink-0 sm:w-36">{c.name}</span>
                <span className="text-muted-foreground">{c.location}</span>
              </li>
            ))}
          </ul>
        </CardContent>
      </Card>

      {/* Step 2: paste the config */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Copy className="h-5 w-5" />
            2. Paste this into your client
          </CardTitle>
          <CardDescription>
            Copy the block and paste it into your client's MCP configuration, or, if it has an "Add
            MCP server" screen, paste the URL and the Authorization header separately. Then restart
            the client.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {!config?.has_api_key ? (
            <Alert className="border-yellow-500 bg-yellow-500/10">
              <AlertCircle className="h-4 w-4" />
              <AlertDescription>
                No API key found for your account. Generate one on the{' '}
                <Link to="/apikey" className="font-bold underline hover:text-primary">
                  API Key
                </Link>{' '}
                page first.
              </AlertDescription>
            </Alert>
          ) : (
            <>
              {/* The two core values */}
              <div className="space-y-2">
                <div className="flex items-center gap-2 rounded-lg bg-muted p-3">
                  <span className="shrink-0 text-xs font-medium text-muted-foreground w-28">
                    Server URL
                  </span>
                  <code className="flex-1 truncate font-mono text-sm">{url}</code>
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-8 w-8 shrink-0"
                    onClick={() => copy(url, 'URL')}
                    title="Copy URL"
                    aria-label="Copy URL"
                  >
                    <Copy className="h-4 w-4" />
                  </Button>
                </div>
                <div className="flex items-center gap-2 rounded-lg bg-muted p-3">
                  <span className="shrink-0 text-xs font-medium text-muted-foreground w-28">
                    Authorization
                  </span>
                  <code className="flex-1 truncate font-mono text-sm">
                    {showKey ? authHeader : `Bearer ${maskedKey}`}
                  </code>
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-8 w-8 shrink-0"
                    onClick={() => setShowKey(!showKey)}
                    title={showKey ? 'Hide key' : 'Show key'}
                    aria-label={showKey ? 'Hide key' : 'Show key'}
                  >
                    {showKey ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                  </Button>
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-8 w-8 shrink-0"
                    onClick={() => copy(authHeader, 'Authorization header')}
                    title="Copy header"
                    aria-label="Copy header"
                  >
                    <Copy className="h-4 w-4" />
                  </Button>
                </div>
              </div>

              {/* The full JSON block */}
              <div className="rounded-lg border bg-muted/50">
                <div className="flex items-center justify-between border-b px-3 py-2">
                  <span className="text-xs font-medium text-muted-foreground">
                    mcpServers config
                  </span>
                  <Button size="sm" variant="outline" onClick={() => copy(blockForCopy, 'Config')}>
                    <Copy className="mr-2 h-4 w-4" />
                    Copy
                  </Button>
                </div>
                <pre className="overflow-x-auto p-3 text-xs">
                  <code className="font-mono">{block}</code>
                </pre>
              </div>

              <Alert>
                <Info className="h-4 w-4" />
                <AlertDescription>
                  This is your existing {name} API key. Over MCP it is limited to reading and
                  writing strategies —{' '}
                  {config?.orders_enabled
                    ? 'and placing orders, because order access is enabled on this server.'
                    : 'it cannot place orders.'}{' '}
                  To revoke access, regenerate the key on the{' '}
                  <Link to="/apikey" className="font-bold underline hover:text-primary">
                    API Key
                  </Link>{' '}
                  page.
                </AlertDescription>
              </Alert>
            </>
          )}
        </CardContent>
      </Card>

      {/* Step 3: verify */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Check className="h-5 w-5" />
            3. Check it worked
          </CardTitle>
          <CardDescription>In your AI client, ask it to confirm the connection.</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="rounded-lg bg-muted p-3">
            <code className="font-mono text-sm">Are you connected to {name}?</code>
          </div>
          <p className="mt-2 text-sm text-muted-foreground">
            It should answer that it is connected and report how many tools are available. You can
            then ask it how a feature works, or to build you a strategy.
          </p>
        </CardContent>
      </Card>
    </div>
  )
}
