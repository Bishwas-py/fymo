#!/usr/bin/env node
import { render } from 'svelte/server';
import { format } from 'node:util';

// stdout carries the binary frame protocol below and nothing else. Component
// code (or any dependency bundled into the SSR output) may call console.log
// during a render; by default Node writes that to stdout, interleaving plain
// text into the frame stream and desyncing the Python parser (issue #84).
// Rebind every stdout-targeting console method to stderr before the stdin
// listener is wired, so no render can ever touch the IPC channel.
// console.error/trace already target stderr and are left alone.
for (const method of ['log', 'info', 'warn', 'debug']) {
    console[method] = (...args) => process.stderr.write(format(...args) + '\n');
}

const cache = new Map();
const stdout = process.stdout;
const stdin = process.stdin;

let buf = Buffer.alloc(0);
let want = null; // bytes of next frame body, or null when reading length

stdin.on('data', chunk => {
    buf = Buffer.concat([buf, chunk]);
    void drain();
});

stdin.on('end', () => process.exit(0));

function writeFrame(obj) {
    const body = Buffer.from(JSON.stringify(obj), 'utf8');
    const len = Buffer.alloc(4);
    len.writeUInt32BE(body.length, 0);
    stdout.write(Buffer.concat([len, body]));
}

async function loadModule(route) {
    if (!cache.has(route)) {
        const url = new URL(`./ssr/${route}.mjs`, import.meta.url);
        cache.set(route, await import(url.href));
    }
    return cache.get(route);
}

async function handle(msg) {
    const { id, type } = msg;
    try {
        if (type === 'ping') {
            writeFrame({ id, ok: true });
            return;
        }
        if (type === 'render') {
            const doc = msg.doc || {};
            globalThis.getDoc = () => doc;
            // Reset per render: the $auth store reads this during SSR,
            // and a leftover value from the previous request must never
            // bleed into the next one.
            globalThis.__fymoIdentity = 'identity' in msg ? msg.identity : null;
            const mod = await loadModule(msg.route);
            const out = render(mod.default, { props: msg.props || {} });
            writeFrame({ id, ok: true, body: out.body, head: out.head });
            return;
        }
        writeFrame({ id, ok: false, error: `unknown type: ${type}`, stack: '' });
    } catch (err) {
        writeFrame({
            id,
            ok: false,
            error: err && err.message ? err.message : String(err),
            stack: err && err.stack ? err.stack : '',
        });
    }
}

async function drain() {
    while (true) {
        if (want === null) {
            if (buf.length < 4) return;
            want = buf.readUInt32BE(0);
            buf = buf.subarray(4);
        }
        if (buf.length < want) return;
        const body = buf.subarray(0, want);
        buf = buf.subarray(want);
        want = null;
        let msg;
        try {
            msg = JSON.parse(body.toString('utf8'));
        } catch (err) {
            writeFrame({ id: 0, ok: false, error: 'invalid JSON frame', stack: err.stack });
            continue;
        }
        await handle(msg);
    }
}
