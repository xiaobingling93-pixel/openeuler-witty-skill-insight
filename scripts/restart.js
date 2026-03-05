#!/usr/bin/env node

const { sleep } = require('./utils.js')

async function run(options) {
  console.log('=== Restarting Witty-Skill-Insight Service ===\n')
  
  const stop = require('./stop.js')
  const start = require('./start.js')
  
  await stop.run(options)
  console.log()
  
  console.log('Waiting for port to release...')
  await sleep(2000)
  console.log()
  
  await start.run(options)
}

module.exports = { run }
