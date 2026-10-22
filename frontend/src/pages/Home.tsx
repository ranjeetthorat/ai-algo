import {
  ArrowRight,
  Blocks,
  Bot,
  CandlestickChart,
  HelpCircle,
  LifeBuoy,
  LogIn,
  Menu,
  Monitor,
  Moon,
  Server,
  ShieldCheck,
  Sigma,
  Sparkles,
  Sun,
  Wand2,
  Zap,
} from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router'
import { BrandLockup } from '@/brand/BrandLockup'
import { BRAND } from '@/brand/brand'
import { Footer } from '@/components/layout/Footer'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from '@/components/ui/sheet'
import { tools } from '@/lib/tools'
import { useThemeStore } from '@/stores/themeStore'

const integrations = [
  'Amibroker',
  'TradingView',
  'GoCharting',
  'Python',
  'MetaTrader',
  'N8N',
  'Java',
  'Go',
  '.NET',
  'Node.js',
  'Rust',
  'ChartInk',
  'Excel',
  'Google Sheets',
  'Telegram',
]

// The surfaces that share one broker session and feed inside a single
// self-hosted instance. Counts come from the code: tools.length is the /tools
// registry, nodeTypes in components/flow/nodes is the Flow palette, and the
// indicator count is what openalgo-charts ships.
const platformDesks = [
  {
    icon: Server,
    title: 'Algo trading on your own server',
    desc: 'One broker API and order engine on your own computer or server. Send orders from TradingView, Amibroker, ChartInk, Excel, Python or an AI assistant.',
  },
  {
    icon: CandlestickChart,
    title: 'Charting platform',
    desc: 'Trade from the chart in the built-in terminal: place and manage orders on the chart itself, with 102 indicators on live market data.',
  },
  {
    icon: Blocks,
    title: 'No-code strategy builder',
    desc: 'Flow is a drag-and-drop canvas: connect 61 node types, from triggers to indicators, conditions and orders, then switch it on to run by itself.',
  },
  {
    icon: Sigma,
    title: 'Options trading platform',
    desc: `${tools.length} built-in tools: option chain, Greeks, OI tracker, max pain, volatility surface, GEX, IV smile, straddles and arbitrage, plus portfolio and SIP backtesters.`,
  },
  {
    icon: Zap,
    title: 'Scalping platform',
    desc: 'A keyboard-driven scalping terminal: arrow keys place CE and PE orders, F6 closes every position and F7 cancels every pending order.',
  },
  {
    icon: ShieldCheck,
    title: 'Sandbox testing',
    desc: 'Analyzer mode runs any strategy on live market data with 1 crore of practice capital and auto square-off at exchange times, without sending real orders.',
  },
]

export default function Home() {
  const { mode, toggleMode } = useThemeStore()
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false)

  const navLinks = [
    { href: '/', label: 'Home', internal: true },
    { href: '/faq', label: 'FAQ', internal: true },
    { href: '/download', label: 'Installation', internal: true },
    { href: BRAND.supportUrl, label: 'Get support', internal: false },
  ]

  return (
    <div className="min-h-screen bg-background flex flex-col">
      {/* Navbar */}
      <header className="sticky top-0 z-30 h-16 w-full border-b bg-background/90 backdrop-blur">
        <nav className="container mx-auto px-4 flex h-full items-center justify-between">
          {/* Logo */}
          <div className="flex items-center gap-2">
            {/* Mobile menu button */}
            <Sheet open={mobileMenuOpen} onOpenChange={setMobileMenuOpen}>
              <SheetTrigger asChild className="lg:hidden">
                <Button variant="ghost" size="icon" aria-label="Open menu">
                  <Menu className="h-5 w-5" />
                </Button>
              </SheetTrigger>
              <SheetContent side="left" className="w-80">
                <SheetHeader className="sr-only">
                  <SheetTitle>Navigation Menu</SheetTitle>
                  <SheetDescription>Main navigation and quick access links</SheetDescription>
                </SheetHeader>
                <div className="flex items-center gap-2 mb-8">
                  <BrandLockup size="md" />
                </div>
                <div className="flex flex-col gap-2">
                  <Link
                    to="/"
                    className="flex items-center gap-2 px-4 py-2 rounded-md hover:bg-accent"
                    onClick={() => setMobileMenuOpen(false)}
                  >
                    <svg
                      xmlns="http://www.w3.org/2000/svg"
                      className="h-5 w-5"
                      fill="none"
                      viewBox="0 0 24 24"
                      stroke="currentColor"
                    >
                      <path
                        strokeLinecap="round"
                        strokeLinejoin="round"
                        strokeWidth={2}
                        d="M3 12l2-2m0 0l7-7 7 7M5 10v10a1 1 0 001 1h3m10-11l2 2m-2-2v10a1 1 0 01-1 1h-3m-6 0a1 1 0 001-1v-4a1 1 0 011-1h2a1 1 0 011 1v4a1 1 0 001 1m-6 0h6"
                      />
                    </svg>
                    Home
                  </Link>
                  <Link
                    to="/faq"
                    className="flex items-center gap-2 px-4 py-2 rounded-md hover:bg-accent"
                    onClick={() => setMobileMenuOpen(false)}
                  >
                    <HelpCircle className="h-5 w-5" />
                    FAQ
                  </Link>
                  <Link
                    to="/download"
                    className="flex items-center gap-2 px-4 py-2 rounded-md bg-primary text-primary-foreground hover:bg-primary/90"
                    onClick={() => setMobileMenuOpen(false)}
                  >
                    <Monitor className="h-5 w-5" />
                    Installation
                  </Link>
                  <a
                    href={BRAND.supportUrl}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="flex items-center gap-2 px-4 py-2 rounded-md hover:bg-accent"
                  >
                    <LifeBuoy className="h-5 w-5" />
                    Get support
                  </a>
                </div>
              </SheetContent>
            </Sheet>

            <Link to="/" className="flex items-center gap-2">
              <BrandLockup hideNameOnMobile />
            </Link>
          </div>

          {/* Desktop Navigation */}
          <div className="hidden lg:flex items-center gap-1">
            {navLinks.map((link) =>
              link.internal ? (
                <Link key={link.href} to={link.href}>
                  <Button variant="ghost" size="sm">
                    {link.label}
                  </Button>
                </Link>
              ) : (
                <a key={link.href} href={link.href} target="_blank" rel="noopener noreferrer">
                  <Button variant="ghost" size="sm">
                    {link.label}
                  </Button>
                </a>
              )
            )}
          </div>

          {/* Right side */}
          <div className="flex items-center gap-2">
            <Link to="/login">
              <Button size="sm">Log in</Button>
            </Link>
            <Button
              variant="ghost"
              size="icon"
              onClick={toggleMode}
              aria-label={mode === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'}
            >
              {mode === 'dark' ? <Sun className="h-5 w-5" /> : <Moon className="h-5 w-5" />}
            </Button>
          </div>
        </nav>
      </header>

      <main className="flex-1">
        {/* Hero Section */}
        <section className="container mx-auto px-4 pt-20 pb-16 sm:pt-28 sm:pb-20">
          <div className="text-center max-w-4xl mx-auto">
            <span className="inline-flex items-center gap-2 rounded-full border border-border bg-card/60 px-4 py-1.5 text-xs font-semibold uppercase tracking-[0.2em] mb-8 shadow-sm">
              <span className="h-1.5 w-1.5 rounded-full bg-emerald-400 shadow-[0_0_8px] shadow-emerald-400/60" />
              <span className="text-brand">{BRAND.displayName}</span>
              <span className="text-muted-foreground">
                - Installed and supported by {BRAND.makerName}
              </span>
            </span>
            <h1 className="text-5xl sm:text-6xl lg:text-7xl font-bold tracking-tight mb-6">
              <span className="block text-balance text-foreground">Automate your trading strategy.</span>
              <span className="block text-primary">Take fast trades.</span>
            </h1>
            <p className="text-lg sm:text-xl font-semibold mb-6 text-primary">
              Algorithmic trading for Indian markets, set up and supported for you
            </p>
            <p className="text-base sm:text-lg text-muted-foreground max-w-2xl mx-auto mb-10">
              Test and run your trading ideas, connect the charting platforms you already use, build
              strategies with AI help, and use the built-in options and portfolio tools - option
              chains and Greeks, portfolio and SIP backtesting - with 30+ brokers.
            </p>
            <div className="flex flex-col sm:flex-row gap-4 justify-center">
              <Button size="lg" asChild>
                <Link to="/login">
                  <LogIn className="mr-2 h-5 w-5" />
                  Log in
                </Link>
              </Button>
              <Button size="lg" variant="outline" asChild>
                <a href={BRAND.supportUrl} target="_blank" rel="noopener noreferrer">
                  <LifeBuoy className="mr-2 h-5 w-5" />
                  Get support
                </a>
              </Button>
            </div>
          </div>
        </section>

        {/* Integrates With */}
        <section className="container mx-auto px-4 py-12 sm:py-16">
          <p className="text-center text-xs sm:text-sm font-semibold uppercase tracking-[0.25em] text-brand mb-6">
            Integrates With
          </p>
          <div className="flex flex-wrap justify-center gap-2 sm:gap-3 max-w-4xl mx-auto">
            {integrations.map((name) => (
              <span
                key={name}
                className="rounded-full border border-border bg-card/60 px-4 py-2 text-sm text-foreground/90 shadow-sm"
              >
                {name}
              </span>
            ))}
          </div>
        </section>

        {/* One platform, many desks */}
        <section className="container mx-auto px-4 py-16 sm:py-20">
          <div className="text-center max-w-3xl mx-auto mb-12">
            <span className="inline-flex items-center gap-1.5 rounded-full border border-brand-soft bg-brand-soft px-3 py-1 text-xs font-semibold uppercase tracking-wider text-brand mb-6">
              <Server className="h-3.5 w-3.5" />
              One platform, many desks
            </span>
            <h2 className="text-3xl sm:text-4xl lg:text-5xl font-bold tracking-tight mb-4">
              Not just an algo trading platform.
              <span className="block text-muted-foreground">A complete trading desk.</span>
            </h2>
            <p className="text-base sm:text-lg text-muted-foreground">
              Placing orders is only the start. Charting, no-code strategy building, options
              analytics, scalping and practice trading all run in the same installation, on your own
              computer or server.
            </p>
          </div>

          <div className="grid gap-5 sm:grid-cols-2 lg:grid-cols-3 max-w-6xl mx-auto">
            {platformDesks.map((desk) => (
              <Card key={desk.title} className="h-full transition-colors hover-border-brand">
                <CardContent className="space-y-3">
                  <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-brand-soft text-brand">
                    <desk.icon className="h-5 w-5" />
                  </div>
                  <h3 className="font-bold text-base">{desk.title}</h3>
                  <p className="text-sm text-muted-foreground leading-relaxed">{desk.desc}</p>
                </CardContent>
              </Card>
            ))}
          </div>
        </section>

        {/* Trade & Research With Your AI */}
        <section className="container mx-auto px-4 py-16 sm:py-20">
          <div className="text-center max-w-3xl mx-auto mb-12">
            <span className="inline-flex items-center gap-1.5 rounded-full border border-emerald-500/30 bg-emerald-500/10 px-3 py-1 text-xs font-semibold uppercase tracking-wider text-emerald-700 dark:text-emerald-400 mb-6">
              <Sparkles className="h-3.5 w-3.5" />
              Made for AI
            </span>
            <h2 className="text-3xl sm:text-4xl lg:text-5xl font-bold tracking-tight mb-4">
              Trade & Research With Your AI
            </h2>
            <p className="text-base sm:text-lg text-muted-foreground">
              Two ways to bring AI into your trading - talk to your account from your AI assistant,
              or use the built-in agent to chart, analyse and draft strategies.
            </p>
          </div>

          <div className="grid gap-6 md:grid-cols-2 max-w-6xl mx-auto">
            {/* MCP card */}
            <Card className="group transition-colors hover:border-purple-400/40">
              <CardContent className="space-y-4">
                <div className="flex items-start gap-4">
                  <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-xl bg-purple-500/10 text-purple-400">
                    <Bot className="h-6 w-6" />
                  </div>
                  <div>
                    <h3 className="text-xl font-bold flex items-center gap-2">
                      {BRAND.displayName} MCP
                      <ArrowRight className="h-5 w-5 transition-transform group-hover:translate-x-0.5" />
                    </h3>
                    <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground mt-1">
                      Trade by Chatting
                    </p>
                  </div>
                </div>
                <p className="text-sm text-muted-foreground leading-relaxed">
                  Connect your {BRAND.displayName} account to Claude, Cursor, Windsurf or ChatGPT.
                  Place orders, check positions and get live prices by asking in plain words.
                </p>
                <div className="flex flex-wrap gap-2 pt-2">
                  {[
                    '25+ built-in actions',
                    'Claude / Cursor / Windsurf / ChatGPT',
                    'Runs on your computer',
                  ].map((tag) => (
                    <span
                      key={tag}
                      className="rounded-md bg-muted px-2.5 py-1 text-xs text-neutral-600 dark:text-neutral-400"
                    >
                      {tag}
                    </span>
                  ))}
                </div>
              </CardContent>
            </Card>

            {/* Built-in agent card */}
            <Card className="group transition-colors hover:border-emerald-400/40">
              <CardContent className="space-y-4">
                <div className="flex items-start gap-4">
                  <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-xl bg-emerald-500/10 text-emerald-400">
                    <Wand2 className="h-6 w-6" />
                  </div>
                  <div>
                    <h3 className="text-xl font-bold flex items-center gap-2">
                      Built-in AI agent
                      <ArrowRight className="h-5 w-5 transition-transform group-hover:translate-x-0.5" />
                    </h3>
                    <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground mt-1">
                      Chat, Chart & Build
                    </p>
                  </div>
                </div>
                <p className="text-sm text-muted-foreground leading-relaxed">
                  An assistant inside {BRAND.displayName} that reads your account and market data,
                  draws charts in the conversation, and drafts Python strategies and Flow workflows
                  for you to review. Uses the AI provider you choose.
                </p>
                <div className="flex flex-wrap gap-2 pt-2">
                  {[
                    'Chat and chart views',
                    'Python and Flow drafts',
                    'Your choice of AI provider',
                  ].map((tag) => (
                    <span
                      key={tag}
                      className="rounded-md bg-muted px-2.5 py-1 text-xs text-neutral-600 dark:text-neutral-400"
                    >
                      {tag}
                    </span>
                  ))}
                </div>
              </CardContent>
            </Card>
          </div>
        </section>
      </main>

      {/* Footer */}
      <Footer />
    </div>
  )
}
