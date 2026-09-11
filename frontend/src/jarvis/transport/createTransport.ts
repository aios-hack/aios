import { createSseTransport } from '@/jarvis/transport/sseTransport';
import type { JarvisTransport } from '@/jarvis/transport/JarvisTransport';

export const createTransport = (): JarvisTransport => createSseTransport();
