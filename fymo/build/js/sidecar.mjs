#!/usr/bin/env node
import { render } from 'svelte/server';

// Provide a no-op getDoc stub for SSR context.
// Components that call getDoc() on the client side will receive an empty
// object during server rendering; the real implementation is injected by
// the Python runtime on the browser side.
globalThis.getDoc = function getDoc() { return {}; };

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
