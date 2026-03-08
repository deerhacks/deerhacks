import './globals.css'
import { PT_Serif } from "next/font/google";
import { UserProvider } from '@auth0/nextjs-auth0/client'

const ptSerif = PT_Serif({
  weight: "400",
  style: "italic",
  subsets: ["latin"],
  display: "swap",
  variable: "--font-pt-serif",
});

export const metadata = {
  title: 'Locatr',
  description: 'Locatr Frontend',
}

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <body className={`${ptSerif.variable}`}>
        <UserProvider>
          {children}
        </UserProvider>
      </body>
    </html>
  )
}
