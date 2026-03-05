#!/usr/bin/env node

const {
  findPidOnPort,
  killProcess,
  getPort
} = require('./utils.js')

async function run(options) {
  const port = getPort(options)
  
  console.log(`=== Stopping Witty-Skill-Insight Service (Port: ${port}) ===\n`)
  
  const pid = findPidOnPort(port)
  
  if (!pid) {
    console.log(`✓ No service running on port ${port}`)
    return
  }
  
  console.log(`Found service running with PID: ${pid}`)
  
  if (killProcess(pid)) {
    console.log('✓ Service stopped successfully')
  } else {
    console.error(`❌ Failed to stop service (PID: ${pid})`)
    console.error('You may need to manually kill the process:')
    console.error(`  kill -9 ${pid}`)
    process.exit(1)
  }
}

module.exports = { run }
