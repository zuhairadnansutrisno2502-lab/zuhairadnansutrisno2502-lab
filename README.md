<a href="https://github.com/zuhairadnansutrisno2502-lab?tab=repositories"><img src="assets/header.svg" width="100%" alt="Xianying — hobby developer. Small CLI tools around git, and Roblox games in Luau."></a>

I mostly make small command-line tools that poke fun at git — each one runs with a single `npx`, nothing to install. These days most of my spare time goes into Roblox games written in Luau.

<sub>TypeScript · Node.js · Luau · Roblox Studio · Swift · Python</sub>

### Selected work

<a href="https://github.com/zuhairadnansutrisno2502-lab/git-sorry"><img src="assets/git-sorry.svg" width="100%" alt="git-sorry — git blame tells you who. git-sorry tells them."></a>

<details>
<summary>Watch it run</summary>
<br>
<img src="https://raw.githubusercontent.com/zuhairadnansutrisno2502-lab/git-sorry/main/docs/demo.gif" width="100%" alt="git-sorry finding the worst line in a repository and reading out the verdict">

```bash
npx git-sorry
```

</details>

<a href="https://github.com/zuhairadnansutrisno2502-lab/blame-roulette"><img src="assets/blame-roulette.svg" width="100%" alt="blame-roulette — one line of code, four suspects. Guess who wrote it."></a>

<details>
<summary>Watch it run</summary>
<br>
<img src="https://raw.githubusercontent.com/zuhairadnansutrisno2502-lab/blame-roulette/main/docs/demo.gif" width="100%" alt="three people taking turns guessing who wrote lines of expressjs/express">

```bash
npx blame-roulette expressjs/express
```

</details>

<a href="https://github.com/zuhairadnansutrisno2502-lab/notmymachine"><img src="assets/notmymachine.svg" width="100%" alt="notmymachine — runs the tests you already have in other timezones and locales."></a>

<details>
<summary>See a real run</summary>

```
  BREAK   Timezone UTC+14 Pacific/Kiritimati exit 1
          It is already tomorrow there, so anything that reads "today"
          off the system clock lands on a different calendar day.

  BREAK   German locale decimal comma, dd.mm.yyyy exit 1
          | 1.2345 !== 1234.5

  pass    Timezone UTC+5:45 Asia/Kathmandu 0.1s
  pass    Empty home directory fresh HOME and XDG dirs 0.1s

  3 of 10 worlds break this suite.
```

```bash
npx notmymachine
```

</details>
