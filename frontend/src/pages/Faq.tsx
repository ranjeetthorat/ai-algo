import { Code, HelpCircle, LifeBuoy, Menu, Monitor, Moon, Sun } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router'
import { BrandLockup } from '@/brand/BrandLockup'
import { BRAND } from '@/brand/brand'
import { Footer } from '@/components/layout/Footer'
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from '@/components/ui/accordion'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from '@/components/ui/sheet'
import { useThemeStore } from '@/stores/themeStore'

const name = BRAND.displayName

const faqData = [
  {
    category: 'General',
    questions: [
      {
        question: `What is ${name}?`,
        answer: `${name} is an algorithmic trading platform for Indian markets. It connects to your broker through one API, so you can send orders from TradingView, Amibroker, Excel, Python or an AI assistant, and switch brokers without rewriting your strategies. ${BRAND.makerName} installs it, sets it up and supports it for you.`,
      },
      {
        question: 'Which brokers are supported?',
        answer: `${name} supports 36 brokers: 5 Paisa, 5 Paisa (XTS), Alice Blue, Angel One, Arrow, CompositEdge, Definedge, Delta Exchange, Dhan, Dhan (Sandbox), Firstock, Flattrade, Fyers, Groww, HDFC Securities, HDFC Sky, Ibulls, IIFL, IIFL Capital, IndMoney, JainamXts, Kotak Securities, Motilal Oswal, mStock by Mirae Asset, Nubra, Paytm Money, Pocketful, RMoney, Samco, Shoonya (Finvasia), TradeSmart, Tradejini, Upstox, Wisdom Capital, Zebu and Zerodha. Delta Exchange is a crypto exchange; the rest are Indian brokers.`,
      },
      {
        question: 'What do I need to run it?',
        answer: `${name} runs on Windows, macOS and Linux. A computer or server with at least 4 GB of RAM and a stable internet connection is enough. You do not need to install anything yourself: ${BRAND.makerName} installs and sets it up for you.`,
      },
      {
        question: `Where can ${name} be installed?`,
        answer: `On your own computer, or on a cloud server so it keeps running when your computer is off. For Indian brokers, a server in India keeps the connection to your broker fast. Broker API orders also need a static IP registered with your broker, which a server provides. ${BRAND.makerName} can advise on the right option and set it up.`,
      },
    ],
  },
  {
    category: 'Costs & Security',
    questions: [
      {
        question: `Is ${name} free and open source?`,
        answer: `${BRAND.productName} is open-source software based on ${BRAND.upstreamName}, licensed under ${BRAND.licenseName}. ${BRAND.makerName} provides installation, setup, custom strategies and ongoing support as a paid service. You also pay your own hosting costs, if you use a server, and your normal brokerage charges.`,
      },
      {
        question: `How secure is ${name}?`,
        answer: `${name} runs on your own computer or server, so your data stays with you. Broker credentials are stored encrypted, and the app uses CSRF protection, rate limiting and secure sessions. Use a strong password and turn on two-factor authentication with your broker wherever it is available.`,
      },
      {
        question: 'Why do I need to log in every day?',
        answer: `Indian brokers end API sessions every day, usually around 3 AM IST, as a security requirement. This comes from your broker, not from ${name}. Logging in again takes a moment, and most brokers support TOTP to make it quicker.`,
      },
    ],
  },
  {
    category: 'Features & Integration',
    questions: [
      {
        question: `Which platforms can I connect to ${name}?`,
        answer: `TradingView (webhooks), Amibroker (AFL), GoCharting, ChartInk, MetaTrader, Excel, Google Sheets, Python, Node.js, Go, N8N, and any platform that can send a webhook. You can also call the REST API from any programming language.`,
      },
      {
        question: 'Can I test a strategy without real orders?',
        answer: `Yes. Analyzer mode gives you 1 crore of practice capital and runs your strategy on live market data, with margin checks and auto square-off at exchange times. It is kept fully separate from live trading, so you can test before you trade with real money.`,
      },
      {
        question: 'Can I run several strategies at the same time?',
        answer: `Yes. Each strategy can have its own webhook, and you can manage and monitor them separately from the dashboard. The Action Center lets you choose how orders from each strategy are handled.`,
      },
      {
        question: `Does ${name} show live market data?`,
        answer: `Yes. ${name} streams live market data from your broker. It is used for live positions and P&L, and your strategies can read it too. The data looks the same whichever broker you use.`,
      },
    ],
  },
  {
    category: 'Licensing & Usage',
    questions: [
      {
        question: `Can I use ${name} for my own trading strategies?`,
        answer: `Yes. You can use ${name} for your personal or proprietary trading. Your strategies remain yours.`,
      },
      {
        question: 'Can someone build a custom strategy for me?',
        answer: `Yes. ${BRAND.makerName} builds custom strategies, alerts and setups as a paid service. Contact support to discuss what you need.`,
      },
      {
        question: 'Can I offer my setup as a service to others?',
        answer: `${BRAND.productName} is licensed under ${BRAND.licenseName}. If you modify it and offer it to other people as a service, the licence requires you to share your source code with them.`,
      },
      {
        question: `Can I use ${name} with AI assistants?`,
        answer: `Yes. ${name} can connect to AI assistants such as Claude, Cursor, Windsurf and ChatGPT, and it has a built-in AI agent. You can check positions, get prices and place orders by asking in plain words.`,
      },
    ],
  },
]

export default function Faq() {
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

      {/* Main Content */}
      <main className="flex-1">
        <div className="container mx-auto px-4 py-12">
          {/* Header */}
          <div className="text-center mb-12">
            <h1 className="text-4xl lg:text-5xl font-bold mb-4">Frequently Asked Questions</h1>
            <p className="text-lg text-muted-foreground max-w-2xl mx-auto">
              Answers to common questions about {BRAND.displayName}, its features, security and
              licensing.
            </p>
          </div>

          {/* FAQ Categories */}
          <div className="max-w-4xl mx-auto space-y-8">
            {faqData.map((category) => (
              <Card key={category.category}>
                <CardHeader>
                  <CardTitle>{category.category}</CardTitle>
                  <CardDescription>
                    {category.category === 'General' &&
                      `Basic information about ${BRAND.displayName}`}
                    {category.category === 'Costs & Security' &&
                      'Pricing, security, and compliance details'}
                    {category.category === 'Features & Integration' &&
                      'Platform capabilities and integrations'}
                    {category.category === 'Licensing & Usage' &&
                      'License terms and usage guidelines'}
                  </CardDescription>
                </CardHeader>
                <CardContent>
                  <Accordion type="single" collapsible className="w-full">
                    {category.questions.map((faq, index) => (
                      <AccordionItem key={index} value={`${category.category}-${index}`}>
                        <AccordionTrigger className="text-left">{faq.question}</AccordionTrigger>
                        <AccordionContent className="text-muted-foreground">
                          {faq.answer}
                        </AccordionContent>
                      </AccordionItem>
                    ))}
                  </Accordion>
                </CardContent>
              </Card>
            ))}
          </div>

          {/* Resources Section */}
          <div className="max-w-4xl mx-auto mt-16">
            <h2 className="text-2xl font-bold text-center mb-8">Need more help?</h2>
            <div className="grid md:grid-cols-3 gap-6">
              <Card className="text-center">
                <CardHeader>
                  <LifeBuoy className="h-10 w-10 mx-auto text-primary" />
                  <CardTitle className="text-lg">Support</CardTitle>
                </CardHeader>
                <CardContent>
                  <p className="text-sm text-muted-foreground mb-4">
                    Questions, problems or custom strategies, {BRAND.makerName} can help
                  </p>
                  <Button variant="outline" asChild>
                    <a href={BRAND.supportUrl} target="_blank" rel="noopener noreferrer">
                      Get support
                    </a>
                  </Button>
                </CardContent>
              </Card>

              <Card className="text-center">
                <CardHeader>
                  <Monitor className="h-10 w-10 mx-auto text-primary" />
                  <CardTitle className="text-lg">Installation</CardTitle>
                </CardHeader>
                <CardContent>
                  <p className="text-sm text-muted-foreground mb-4">
                    Get {BRAND.displayName} installed, or add another computer
                  </p>
                  <Button variant="outline" asChild>
                    <Link to="/download">Installation help</Link>
                  </Button>
                </CardContent>
              </Card>

              <Card className="text-center">
                <CardHeader>
                  <Code className="h-10 w-10 mx-auto text-primary" />
                  <CardTitle className="text-lg">Source code</CardTitle>
                </CardHeader>
                <CardContent>
                  <p className="text-sm text-muted-foreground mb-4">
                    {BRAND.productName} is open source under {BRAND.licenseName}
                  </p>
                  <Button variant="outline" asChild>
                    <a href={BRAND.sourceUrl} target="_blank" rel="noopener noreferrer">
                      View source code
                    </a>
                  </Button>
                </CardContent>
              </Card>
            </div>
          </div>
        </div>
      </main>

      {/* Footer */}
      <Footer />
    </div>
  )
}
