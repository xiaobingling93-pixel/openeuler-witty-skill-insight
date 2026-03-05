#!/usr/bin/env node

const { execSync } = require('child_process')
const fs = require('fs')
const path = require('path')

const {
  ensureEnvFile,
  ensureDataDirectory,
  runCommand
} = require('./utils.js')

console.log('=== Witty-Skill-Insight Post-Install Initialization ===\n')

try {
  ensureEnvFile()
  console.log()
  
  ensureDataDirectory()
  console.log()
  
  console.log('Syncing database schema...')
  execSync('npx prisma db push', { stdio: 'inherit' })
  console.log('✓ Database schema synced')
  console.log()
  
  console.log('Generating Prisma client...')
  execSync('npx prisma generate', { stdio: 'inherit' })
  console.log('✓ Prisma client generated')
  console.log()
  
  console.log('=== Initialization Complete ===')
  console.log('\nStart the service with:')
  console.log('  npx witty-skill-insight start')
  console.log('\nOr specify a custom port:')
  console.log('  npx witty-skill-insight start --port 3001')
  console.log('\nAccess the dashboard at: http://localhost:3000')
} catch (error) {
  console.error('\n❌ Initialization failed:', error.message)
  process.exit(1)
}
