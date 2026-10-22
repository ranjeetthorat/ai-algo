import { LifeBuoy, Monitor, Server } from 'lucide-react'
import { BRAND } from '@/brand/brand'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'

const helpTopics = [
  {
    title: 'On your computer',
    description: `We install ${BRAND.displayName} on your Windows, Mac or Linux computer, connect your broker and check that everything works before you trade.`,
    icon: Monitor,
  },
  {
    title: 'On your server',
    description: `For trading that keeps running when your computer is off, we set up ${BRAND.displayName} on a cloud server with a static IP, as SEBI requires for API orders.`,
    icon: Server,
  },
  {
    title: 'Adding a computer',
    description: `Want to use ${BRAND.displayName} from another computer, or move it to a new one? Contact support and we will set it up for you.`,
    icon: LifeBuoy,
  },
]

export default function Download() {
  return (
    <div className="container mx-auto px-4 py-8 max-w-4xl">
      <h1 className="text-4xl font-bold text-center mb-4">
        Get help <span className="text-primary">installing</span>
      </h1>
      <p className="text-center text-muted-foreground mb-8">
        {BRAND.displayName} is installed and set up for you by {BRAND.makerName}, on your computer
        or your server. There is nothing to download.
      </p>

      <div className="grid gap-4 md:grid-cols-3 mb-8">
        {helpTopics.map((topic) => (
          <Card key={topic.title}>
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-lg">
                <topic.icon className="h-5 w-5" />
                {topic.title}
              </CardTitle>
            </CardHeader>
            <CardContent>
              <CardDescription>{topic.description}</CardDescription>
            </CardContent>
          </Card>
        ))}
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Get it installed</CardTitle>
          <CardDescription>
            To get {BRAND.displayName} installed, or to add a computer, contact support. We will
            agree a time and do the setup with you.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Button asChild>
            <a href={BRAND.supportUrl} target="_blank" rel="noopener noreferrer">
              Get support
            </a>
          </Button>
        </CardContent>
      </Card>
    </div>
  )
}
