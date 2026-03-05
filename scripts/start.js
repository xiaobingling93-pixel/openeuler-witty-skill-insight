#!/usr/bin/env node

const { spawn } = require('child_process')
const fs = require('fs')
const path = require('path')

const {
  findPidOnPort,
  killProcess,
  getPort,
  ensureEnvFile,
  runCommand,
  sleep
} = require('./utils.js')

async function run(options) {
  const port = getPort(options)
  
  console.log('=== Starting Witty-Skill-Insight Service ===\n')
  
  ensureEnvFile()
  console.log()
  
  const existingPid = findPidOnPort(port)
  if (existingPid) {
    console.log(`⚠️  Port ${port} is already in use by PID: ${existingPid}`)
    console.log('Please stop the existing service first or use a different port.')
    console.log(`\nTo stop: npx witty-skill-insight stop --port ${port}`)
    process.exit(1)
  }
  
  try {
    console.log('Syncing database schema...')
    await runCommand('npx prisma db push')
    console.log('✓ Database schema synced')
    console.log()
    
    console.log('Generating Prisma client...')
    await runCommand('npx prisma generate')
    console.log('✓ Prisma client generated')
    console.log()
  } catch (error) {
    console.error('❌ Database initialization failed:', error.message)
    process.exit(1)
  }
  
  console.log(`Starting server on port ${port}...`)
  
  const logPath = path.join(process.cwd(), 'server.log')
  const env = { ...process.env, PORT: port.toString() }
  
  const proc = spawn('npm', ['run', 'dev'], {
    stdio: ['ignore', 'pipe', 'pipe'],
    env,
    detached: true
  })
  
  const logStream = fs.createWriteStream(logPath, { flags: 'a' })
  proc.stdout.pipe(logStream)
  proc.stderr.pipe(logStream)
  
  proc.unref()
  
  await sleep(3000)
  
  const pid = findPidOnPort(port)
  if (pid) {
    console.log('✓ Server started successfully')
    console.log(`  PID: ${pid}`)
    console.log(`  Port: ${port}`)
    console.log(`  Log: ${logPath}`)
    console.log(`  URL: http://localhost:${port}`)
  } else {
    console.error('❌ Failed to start server. Check server.log for details.')
    process.exit(1)
  }
}

module.exports = { run }
