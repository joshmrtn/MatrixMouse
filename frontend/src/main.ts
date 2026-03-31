/**
 * MatrixMouse Frontend - Main Entry Point
 */

import './styles/variables.css';
import './styles/reset.css';
import './styles/layout.css';
import './styles/components.css';

import { App } from './app';

// Initialize application
const app = new App();
app.init();
