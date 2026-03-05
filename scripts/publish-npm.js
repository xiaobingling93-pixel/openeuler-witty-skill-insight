#!/usr/bin/env node

const { execSync } = require('child_process')
const fs = require('fs')
const path = require('path')

function runCommand(command, description) {
  console.log(`\n${description}...`)
  console.log(`$ ${command}`)
  try {
    execSync(command, { stdio: 'inherit' })
    console.log('✓ Success')
  } catch (error) {
    console.error('✗ Failed')
    process.exit(1)
  }
}

function incrementVersion(version, type = 'patch') {
  const parts = version.split('.').map(Number)
  
  if (type === 'major') {
    parts[0]++
    parts[1] = 0
    parts[2] = 0
  } else if (type === 'minor') {
    parts[1]++
    parts[2] = 0
  } else {
    parts[2]++
  }
  
  return parts.join('.')
}

function main() {
  console.log('=== NPM Package Publishing Script ===\n')
  
  const args = process.argv.slice(2)
  const typeIndex = args.indexOf('--type')
  const type = typeIndex !== -1 ? args[typeIndex + 1] : 'patch'
  const dryRun = args.includes('--dry-run')
  
  if (!['patch', 'minor', 'major'].includes(type)) {
    console.error('Invalid version type. Use: patch, minor, or major')
    process.exit(1)
  }
  
  console.log(`Configuration:`)
  console.log(`  Version type: ${type}`)
  console.log(`  Dry run: ${dryRun ? 'Yes' : 'No'}`)
  
  runCommand('git diff --quiet || true', 'Checking git working directory')
  
  try {
    const packageJsonPath = path.join(process.cwd(), 'package.json')
    
    if (!fs.existsSync(packageJsonPath)) {
      console.error('package.json not found')
      process.exit(1)
    }
    
    const packageJson = JSON.parse(fs.readFileSync(packageJsonPath, 'utf8'))
    
    if (!packageJson.version) {
      console.error('package.json missing version field')
      process.exit(1)
    }
    
    const currentVersion = packageJson.version
    const newVersion = incrementVersion(currentVersion, type)
    
    console.log(`\nVersion bump: ${currentVersion} → ${newVersion}`)
    
    packageJson.version = newVersion
    fs.writeFileSync(packageJsonPath, JSON.stringify(packageJson, null, 2) + '\n')
    
    console.log(`✓ Updated package.json to version ${newVersion}`)
    
    runCommand('git add package.json', 'Staging package.json')
    runCommand(`git commit -m "chore: bump version to ${newVersion}"`, 'Committing version bump')
    
    runCommand('npm ci', 'Installing dependencies')
    
    if (fs.existsSync('eslint.config.mjs')) {
      runCommand('npm run lint', 'Running linter')
    }
    
    runCommand('npm run build', 'Building project')
    
    if (dryRun) {
      console.log('\n=== Dry Run Complete ===')
      console.log('To publish, run without --dry-run flag')
    } else {
      try {
        execSync('npm whoami', { stdio: 'ignore' })
      } catch (error) {
        console.error('\n⚠️  Warning: Not logged in to npm')
        console.error('Please run: npm login')
        process.exit(1)
      }
      
      runCommand('npm publish', 'Publishing to npm')
      
      console.log('\n=== Publishing Complete ===')
      console.log(`\nPackage published: ${packageJson.name}@${newVersion}`)
      console.log('\nInstall with:')
      console.log(`  npm install ${packageJson.name}`)
    }
  } catch (error) {
    console.error('\n❌ Error:', error.message)
    process.exit(1)
  }
}

main()
