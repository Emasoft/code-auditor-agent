#!/usr/bin/env node
// Fixture CLI exercising the three yargs registration forms the
// discoverer must handle:
//   1. Inline-string form with no builder.
//   2. Object form with a builder map plus describe.
//   3. Inline-string form with a builder lambda calling .option(...).
const yargs = require('yargs');

yargs(process.argv.slice(2))
  .command(
    'greet <name>',
    'Print a friendly greeting to the named user.',
    () => {},
    (argv) => {
      console.log(`hello ${argv.name}`);
    }
  )
  .command({
    command: 'goodbye [user]',
    describe: 'Wave goodbye to the named user before exiting.',
    builder: {
      loud: {
        type: 'boolean',
        default: false,
        describe: 'Shout the farewell in uppercase.',
      },
    },
    handler: (argv) => {
      const text = `goodbye ${argv.user || 'world'}`;
      console.log(argv.loud ? text.toUpperCase() : text);
    },
  })
  .command(
    'sync <src> <dst>',
    'Copy files between two locations on disk.',
    (yargs) => {
      return yargs
        .option('dry-run', {
          alias: 'n',
          type: 'boolean',
          default: false,
          describe: 'Print the plan without performing the copy.',
        })
        .option('verbose', {
          alias: 'v',
          type: 'boolean',
          default: false,
          describe: 'Emit per-file progress.',
        });
    },
    (argv) => {
      if (argv['dry-run']) {
        console.log(`would copy ${argv.src} -> ${argv.dst}`);
      } else {
        console.log(`copying ${argv.src} -> ${argv.dst}`);
      }
    }
  )
  .demandCommand(1, 'You must specify a subcommand to run.')
  .strict()
  .parse();
