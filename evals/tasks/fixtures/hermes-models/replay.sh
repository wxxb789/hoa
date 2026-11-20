# Source in Bash from the fixture root. This is a local replay, not an API client.
route_replay() {
    local profile=$1 action=$2 argument=$3
    local alias provider model effort spare replacement state fallback=false
    local home endpoint candidate status session report
    case $profile in root|inbox) ;; *) return 2 ;; esac
    read -r alias provider model effort spare replacement < "$profile.preset"
    session=$profile-probe

    case $action in
        chat)
            [[ $argument == clarify ]] || return 2
            while read -r home endpoint candidate status; do
                if [[ $home == "$profile" && $endpoint == "$provider" && $candidate == "$model" ]]; then
                    state=$status
                fi
            done < adapter-replay.txt
            if [[ $state != ok ]]; then
                provider=$spare
                model=$replacement
                fallback=true
            fi
            printf '%s\n' "$model" > "$profile-session.state"
            report="PROBE_OK session=$session fallback_active=$fallback provider=$provider"
            ;;
        session|reasoning)
            [[ $argument == "$session" && -f $profile-session.state ]] || return 2
            read -r model < "$profile-session.state"
            report="session=$session model=$model"
            if [[ $action == reasoning ]]; then
                local level
                while read -r home candidate level; do
                    if [[ $home == "$profile" && $candidate == "$model" ]]; then effort=$level; fi
                done < overrides.txt
                report+=" effort=$effort"
            fi
            ;;
        *) return 2 ;;
    esac
    printf '%s\n' "$report" > "$profile-$action.txt"
    printf '%s\n' "$report"
}

route_replay "${1:-}" "${2:-}" "${3:-}"
