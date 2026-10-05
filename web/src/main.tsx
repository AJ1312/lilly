import '@fontsource-variable/fraunces'
import '@fontsource-variable/instrument-sans'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import App from './App'
import { applyTheme, useApp } from './store'
import './styles.css'

applyTheme(useApp.getState().theme)

const root = document.getElementById('root')
if (root) createRoot(root).render(<StrictMode><App /></StrictMode>)
