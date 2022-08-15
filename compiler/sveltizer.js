const sveltizer = require("svelte/compiler");
const fs = require('fs');
const path = require('path');


const pathToComponent = path.join(__dirname, '../templates/comments/index.svelte')

const svelteCode = fs.readFileSync(pathToComponent, 'utf-8')

const {js, css} = sveltizer.compile(svelteCode, {
})

console.log(js)